import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.agents import invoke_runtime
from app.auth import current_user
from app.config import get_settings
from app.db import Base, get_db, get_engine, session_factory
from app.models import Agent, AutomationJob, Event, Payment, Task, User
from app.schemas import (
    AgentCreate,
    BudgetUpdate,
    Rating,
    Selection,
    TaskCreate,
    WalletBind,
    money,
)
from app.seed import seed_demo
from app.service import agent_view, dispatch, payment_view
from app.showcase import readable_task, shared_ids, task_visibility, visible_task_view
from app.wallets import (
    authorize_wallet_owner,
    bind_existing_wallet,
    delegated_payment_limit,
    inspect_existing_wallet,
    validate_wallet_binding,
)

logger = logging.getLogger("marketplace")


@asynccontextmanager
async def lifespan(app):
    settings = get_settings()
    settings.validate_api()
    if settings.app_mode == "demo":
        Base.metadata.create_all(get_engine())
        with session_factory()() as db:
            seed_demo(db)
    yield


app = FastAPI(title="Agent Marketplace API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins.split(","),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    # Do not log request bodies, wallet credentials, payment proofs, or provider errors.
    logger.error(
        "Request failed: %s %s (%s)",
        request.method,
        request.url.path,
        type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "The request could not be completed. Please refresh and try again."
        },
    )


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "healthy"}


@app.get("/api/config")
def config():
    s = get_settings()
    return {
        "mode": s.app_mode,
        "network": "Base Sepolia"
        if s.chain_network == "eip155:84532"
        else s.chain_network,
        "cognito_domain": s.cognito_domain,
        "cognito_client_id": s.cognito_client_id,
        "cognito_region": s.aws_region,
        "runtime": "Amazon Bedrock AgentCore"
        if s.app_mode == "aws"
        else "Local runtime",
        "payments": "AgentCore Payments"
        if s.app_mode == "aws"
        else "Simulated payments",
        "chain_sync": False,
    }


@app.get("/api/me")
def me(user: User = Depends(current_user)):
    limit = delegated_payment_limit(user.id)
    budget = min(user.budget_micros, limit) if limit is not None else user.budget_micros
    return {
        "id": user.id,
        "name": user.name,
        "budget": money(budget),
        "spent": money(user.spent_micros),
        "reserved": money(user.reserved_micros),
        "remaining": money(budget - user.spent_micros - user.reserved_micros),
        "wallet_connected": bool(user.payment_instrument_id),
        "wallet_url": user.wallet_url,
        "wallet_address": user.wallet_address,
        "wallet_provider": "Stripe / Privy",
        "wallet_shared": limit is not None,
        "payment_limit": money(limit) if limit is not None else None,
    }


@app.get("/api/agents")
def agents(
    q: str = Query("", max_length=100),
    category: str = "",
    mine: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    query = select(Agent).where(Agent.active.is_(True))
    if category:
        query = query.where(Agent.category == category)
    if mine:
        query = query.where(
            or_(Agent.owner_id == user.id, Agent.id.in_(shared_ids(user, "agent")))
        )
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(
            Agent.name.ilike(f"%{escaped}%", escape="\\")
            | Agent.description.ilike(f"%{escaped}%", escape="\\")
        )
    return [
        {
            **agent_view(a),
            "read_only": a.owner_id != user.id and a.id in shared_ids(user, "agent"),
        }
        for a in db.scalars(
            query.order_by(Agent.featured.desc(), Agent.created_at).limit(200)
        )
    ]


@app.get("/api/tasks")
def tasks(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [
        visible_task_view(t, db, user)
        for t in db.scalars(
            select(Task)
            .where(task_visibility(user))
            .order_by(Task.created_at.desc())
            .limit(100)
        )
    ]


@app.get("/api/tasks/{task_id}")
def get_task(
    task_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    return visible_task_view(readable_task(db, task_id, user), db, user)


@app.get("/api/payments")
def payments(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [
        {**payment_view(p, db), "read_only": p.owner_id != user.id}
        for p in db.scalars(
            select(Payment)
            .where(
                or_(
                    Payment.owner_id == user.id,
                    Payment.task_id.in_(shared_ids(user, "task")),
                )
            )
            .order_by(Payment.created_at.desc())
            .limit(200)
        )
    ]


@app.get("/api/overview")
def overview(db: Session = Depends(get_db), user: User = Depends(current_user)):
    events = db.scalars(
        select(Event)
        .where(
            or_(Event.owner_id == user.id, Event.task_id.in_(shared_ids(user, "task")))
        )
        .order_by(Event.created_at.desc())
        .limit(12)
    )
    return {
        "agents": db.scalar(
            select(func.count()).select_from(Agent).where(Agent.active.is_(True))
        ),
        "tasks": db.scalar(
            select(func.count()).select_from(Task).where(task_visibility(user))
        ),
        "completed": db.scalar(
            select(func.count())
            .select_from(Task)
            .where(task_visibility(user), Task.status == "completed")
        ),
        "spent": money(user.spent_micros),
        "events": [
            {
                "id": e.id,
                "kind": e.kind,
                "message": e.message,
                "task_id": e.task_id,
                "created_at": e.created_at,
            }
            for e in events
        ],
    }


def execute(db, user, action, data=None, task_id=None):
    if task_id and readable_task(db, task_id, user).owner_id != user.id:
        raise HTTPException(403, "Shared demo tasks are read-only.")
    if task_id and action != "start_automation":
        job = db.get(AutomationJob, task_id)
        if job and job.status in {"queued", "running"}:
            raise HTTPException(
                409,
                "This task is running automatically. Its progress will update shortly.",
            )
    settings = get_settings()
    payload = {
        "user_id": user.id,
        "action": action,
        "data": data or {},
        "task_id": task_id,
    }
    if settings.app_mode == "aws":
        # User identity is derived from the verified JWT, never browser input.
        return invoke_runtime(settings.orchestrator_runtime_arn, payload)
    return dispatch(db, **payload)


@app.post("/api/tasks", status_code=201)
def post_task(
    body: TaskCreate, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    return execute(db, user, "create_task", body.model_dump(mode="json"))


@app.post("/api/agents", status_code=201)
def post_agent(
    body: AgentCreate, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    return execute(db, user, "publish_agent", body.model_dump(mode="json"))


@app.post("/api/tasks/{task_id}/quote")
def quote(
    task_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    return execute(db, user, "quote_marketplace", task_id=task_id)


@app.post("/api/tasks/{task_id}/select")
def select_winner(
    task_id: str,
    body: Selection,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return execute(db, user, "select_bid", body.model_dump(), task_id)


@app.post("/api/tasks/{task_id}/pay")
def pay(
    task_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    return execute(db, user, "process_payment", task_id=task_id)


@app.post("/api/tasks/{task_id}/auto-select")
def auto_select_winner(
    task_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    return execute(db, user, "auto_select_bid", task_id=task_id)


@app.post("/api/tasks/{task_id}/automate")
def automate(
    task_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    return execute(db, user, "start_automation", task_id=task_id)


@app.post("/api/tasks/{task_id}/deliver")
def deliver(
    task_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    return execute(db, user, "settle_marketplace", task_id=task_id)


@app.post("/api/tasks/{task_id}/rate")
def rate(
    task_id: str,
    body: Rating,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return execute(db, user, "rate_task", body.model_dump(), task_id)


@app.patch("/api/me/budget")
def budget(
    body: BudgetUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return execute(db, user, "update_budget", body.model_dump(mode="json"))


@app.post("/api/me/wallet")
def wallet(
    body: WalletBind, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    if get_settings().app_mode == "demo":
        return {
            "wallet_url": None,
            "message": "Demo mode uses simulated USDC. Your existing wallet is not accessed.",
        }
    return bind_existing_wallet(db, user)


@app.get("/api/me/wallet")
def wallet_status(user: User = Depends(current_user)):
    if get_settings().app_mode == "demo":
        return {
            "provider": "Stripe / Privy",
            "status": "DEMO",
            "balance": None,
            "address": None,
            "network": "Base Sepolia",
            "wallet_url": None,
        }
    settings = authorize_wallet_owner(user)
    if not user.payment_instrument_id:
        raise HTTPException(409, "Connect your existing Stripe/Privy wallet first")
    validate_wallet_binding(user, settings)
    return inspect_existing_wallet(settings)
