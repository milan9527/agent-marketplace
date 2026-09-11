from datetime import datetime, timezone
from fractions import Fraction

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.agents import call_bidders
from app.config import get_settings
from app.models import Agent, Bid, Event, Payment, Task, User
from app.payments import PaymentUncertain, settle_payment
from app.seed import is_demo_profile
from app.schemas import (
    AgentCreate,
    BudgetUpdate,
    Rating,
    Selection,
    TaskCreate,
    micros,
    money,
)

MIN_AUTO_MATCH = 70


def ranked_bids(task, db):
    bids = db.scalars(select(Bid).where(Bid.task_id == task.id)).all()
    return sorted(
        bids,
        key=lambda b: (
            b.price_micros > task.budget_micros,
            -Fraction(b.match_score * b.quality_score, b.price_micros),
            -b.match_score,
            -b.quality_score,
            b.price_micros,
            b.agent_id,
        ),
    )


def recommended_bid(task, db):
    for bid in ranked_bids(task, db):
        agent = db.get(Agent, bid.agent_id)
        if (
            bid.price_micros <= task.budget_micros
            and bid.match_score >= MIN_AUTO_MATCH
            and agent.active
            and (
                task.agent_scope == "all"
                or is_demo_profile(agent) == (task.agent_scope == "demo")
            )
        ):
            return bid
    return None


def record(db, user_id, kind, message, task_id=None):
    db.add(Event(owner_id=user_id, kind=kind, message=message, task_id=task_id))


def agent_view(a: Agent) -> dict:
    return {
        "id": a.id,
        "name": a.name,
        "tagline": a.tagline,
        "description": a.description,
        "category": a.category,
        "skills": a.skills,
        "price": money(a.price_micros),
        "wallet": None if is_demo_profile(a) else a.wallet,
        "is_demo": is_demo_profile(a),
        "bookable": a.active,
        "color": a.color,
        "icon": a.icon,
        "featured": a.featured,
        "active": a.active,
        "completed_tasks": a.completed_tasks,
        "rating": round(a.reputation_total / a.reputation_count, 1)
        if a.reputation_count
        else None,
        "review_count": a.reputation_count,
        "created_at": a.created_at,
    }


def payment_view(p: Payment, db) -> dict:
    agent, task = db.get(Agent, p.agent_id), db.get(Task, p.task_id)
    return {
        "id": p.id,
        "task_id": p.task_id,
        "task_title": task.title,
        "agent_name": agent.name,
        "amount": money(p.amount_micros),
        "status": p.status,
        "provider": p.provider,
        "transaction_hash": p.transaction_hash,
        "error": p.error,
        "created_at": p.created_at,
    }


def task_view(task: Task, db: Session) -> dict:
    bids = ranked_bids(task, db)
    bid_views = []
    for bid in bids:
        bid_views.append(
            {
                "id": bid.id,
                "agent": agent_view(db.get(Agent, bid.agent_id)),
                "price": money(bid.price_micros),
                "match_score": bid.match_score,
                "quality_score": bid.quality_score,
                "rationale": bid.rationale,
                "within_budget": bid.price_micros <= task.budget_micros,
                "value_score": round(
                    bid.match_score * bid.quality_score / bid.price_micros, 8
                ),
            }
        )
    recommended = recommended_bid(task, db) if task.status == "bidding" else None
    payment = db.scalar(select(Payment).where(Payment.task_id == task.id))
    selected = task.winner_id or task.preferred_agent_id
    demo = (
        is_demo_profile(db.get(Agent, selected))
        if selected
        else bool(bid_views) and all(b["agent"]["is_demo"] for b in bid_views)
    )
    return {
        "id": task.id,
        "title": task.title,
        "spec": task.spec,
        "category": task.category,
        "budget": money(task.budget_micros),
        "status": task.status,
        "is_demo": demo,
        "selection_mode": task.selection_mode,
        "agent_scope": task.agent_scope,
        "selection_reason": task.selection_reason,
        "recommended_bid_id": recommended.id if recommended else None,
        "minimum_auto_match": MIN_AUTO_MATCH,
        "deadline": task.deadline,
        "winner_id": task.winner_id,
        "created_at": task.created_at,
        "bids": bid_views,
        "delivery": task.delivery,
        "rating": task.rating,
        "payment": payment_view(payment, db) if payment else None,
    }


def owned_task(db, task_id, user_id) -> Task:
    task = db.scalar(select(Task).where(Task.id == task_id, Task.owner_id == user_id))
    if not task:
        raise HTTPException(404, "Task not found")
    return task


def check_deadline(task):
    if datetime.fromisoformat(task.deadline) <= datetime.now(timezone.utc):
        raise HTTPException(
            409, "This task has expired. Publish a new task to continue."
        )


def require_bookable_agent(agent: Agent):
    if not agent.active:
        raise HTTPException(409, "This agent is no longer available.")


def transition(db, task, expected, target):
    result = db.execute(
        update(Task)
        .where(Task.id == task.id, Task.status.in_(expected))
        .values(status=target)
        .execution_options(synchronize_session=False)
    )
    if not result.rowcount:
        db.rollback()
        raise HTTPException(
            409,
            "This task is already being processed. Refresh to see its current state.",
        )
    db.commit()
    db.refresh(task)


def create_task(db, user_id, data):
    body = TaskCreate.model_validate(data)
    if body.preferred_agent_id:
        agent = db.get(Agent, body.preferred_agent_id)
        if not agent:
            raise HTTPException(404, "Agent not found")
        require_bookable_agent(agent)
        if body.agent_scope != "all" and is_demo_profile(agent) != (
            body.agent_scope == "demo"
        ):
            raise HTTPException(
                422, "The selected agent does not match the requested agent pool."
            )
    task = Task(
        owner_id=user_id,
        title=body.title,
        spec=body.spec,
        category=body.category,
        budget_micros=micros(body.budget),
        deadline=body.deadline.isoformat(),
        preferred_agent_id=body.preferred_agent_id,
        selection_mode=body.selection_mode,
        agent_scope=body.agent_scope,
    )
    db.add(task)
    db.flush()
    record(db, user_id, "task_posted", f'Published "{task.title}"', task.id)
    db.commit()
    return task_view(task, db)


def quote_marketplace(db, user_id, task_id):
    task = owned_task(db, task_id, user_id)
    if task.selection_mode == "auto" and task.winner_id:
        return task_view(task, db)
    if task.status == "bidding":
        if task.selection_mode == "auto":
            return auto_select_bid(db, user_id, task_id)
        return task_view(task, db)
    if task.status != "open":
        raise HTTPException(409, "Only open tasks can collect bids")
    check_deadline(task)
    candidates = select(Agent).where(Agent.active.is_(True))
    if task.preferred_agent_id:
        candidates = candidates.where(Agent.id == task.preferred_agent_id)
    # Demo identity comes from the same server-owned fields used by payment guards.
    from app.seed import DEMO_CATALOG_OWNER

    demo_filter = (Agent.owner_id == DEMO_CATALOG_OWNER) | Agent.wallet.startswith(
        "demo:"
    )
    if task.agent_scope == "demo":
        candidates = candidates.where(demo_filter)
    elif task.agent_scope == "live":
        candidates = candidates.where(~demo_filter)
    agents = list(
        db.scalars(
            candidates.order_by(
                (Agent.category == task.category).desc(), Agent.price_micros
            ).limit(20)
        )
    )
    if not agents:
        raise HTTPException(
            409,
            "No agents are available in this pool. Choose another pool or publish an agent.",
        )
    transition(db, task, ["open"], "quoting")
    try:
        result = call_bidders(
            {
                "action": "quote",
                "task": {
                    "title": task.title,
                    "spec": task.spec,
                    "category": task.category,
                },
                "agents": [agent_view(a) for a in agents],
            }
        )
        evaluations = {e["agent_id"]: e for e in result["bids"]}
        count = 0
        for agent in agents:
            evaluation = evaluations.get(agent.id)
            if evaluation is None:
                continue
            quality = (
                round(agent.reputation_total / agent.reputation_count * 20)
                if agent.reputation_count
                else 80
            )
            db.add(
                Bid(
                    task_id=task.id,
                    agent_id=agent.id,
                    price_micros=agent.price_micros,
                    match_score=max(1, min(100, int(evaluation["match_score"]))),
                    quality_score=quality,
                    rationale=str(evaluation["rationale"])[:1000],
                )
            )
            count += 1
        if not count:
            raise ValueError("No bids returned")
        task.status = "bidding"
        record(
            db,
            user_id,
            "bids_received",
            f'{count} specialists submitted bids for "{task.title}"',
            task.id,
        )
        db.commit()
    except Exception:
        db.rollback()
        task = db.get(Task, task_id)
        task.status = "open"
        db.commit()
        raise HTTPException(
            502, "Could not collect bids. You can safely try again."
        ) from None
    if task.selection_mode == "auto":
        return auto_select_bid(db, user_id, task_id)
    return task_view(task, db)


def select_bid(db, user_id, task_id, data, *, automatic=False):
    body = Selection.model_validate(data)
    task = owned_task(db, task_id, user_id)
    check_deadline(task)
    bid = db.scalar(select(Bid).where(Bid.id == body.bid_id, Bid.task_id == task.id))
    if not bid:
        raise HTTPException(404, "Bid not found")
    agent = db.get(Agent, bid.agent_id)
    require_bookable_agent(agent)
    if task.agent_scope != "all" and is_demo_profile(agent) != (
        task.agent_scope == "demo"
    ):
        raise HTTPException(409, "This agent no longer matches the task's agent pool.")
    if bid.price_micros > task.budget_micros:
        raise HTTPException(422, "This bid exceeds the task budget")
    reason = (
        f"Automatically selected {agent.name}: highest quality × match / price among active agents "
        f"within the {money(task.budget_micros)} USDC budget and at least {MIN_AUTO_MATCH}% match. "
        f"Match {bid.match_score}%, quality {bid.quality_score}/100, "
        f"{'example quote' if is_demo_profile(agent) else 'price'} {money(bid.price_micros)} USDC."
        if automatic
        else f"Manually selected {agent.name}."
    )
    result = db.execute(
        update(Task)
        .where(Task.id == task.id, Task.status == "bidding")
        .values(
            winner_id=bid.agent_id,
            status="demo_ready" if is_demo_profile(agent) else "awaiting_payment",
            selection_mode="auto" if automatic else "manual",
            selection_reason=reason,
        )
    )
    if not result.rowcount:
        raise HTTPException(
            409, "A winner has already been selected or the task is not accepting bids"
        )
    record(
        db,
        user_id,
        "winner_selected",
        reason + (" for a free demo" if is_demo_profile(agent) else ""),
        task.id,
    )
    db.commit()
    db.refresh(task)
    return task_view(task, db)


def auto_select_bid(db, user_id, task_id):
    task = owned_task(db, task_id, user_id)
    if task.winner_id:
        return task_view(task, db)
    if task.status != "bidding":
        raise HTTPException(409, "Collect bids before choosing automatically.")
    check_deadline(task)
    bid = recommended_bid(task, db)
    if not bid:
        reason = (
            f"No active agent meets both the task budget and the {MIN_AUTO_MATCH}% minimum match. "
            "Review the bids manually or post a task with a revised brief or budget."
        )
        db.execute(
            update(Task)
            .where(
                Task.id == task.id, Task.status == "bidding", Task.winner_id.is_(None)
            )
            .values(selection_reason=reason)
        )
        db.commit()
        db.refresh(task)
        return task_view(task, db)
    return select_bid(db, user_id, task_id, {"bid_id": bid.id}, automatic=True)


def process_payment(db, user_id, task_id):
    task = owned_task(db, task_id, user_id)
    if task.winner_id and is_demo_profile(db.get(Agent, task.winner_id)):
        raise HTTPException(
            409, "Demo runs are free. Use Run demo to get your deliverable."
        )
    existing = db.scalar(select(Payment).where(Payment.task_id == task.id))
    if existing:
        if existing.status == "settled":
            return task_view(task, db)
        raise HTTPException(
            409, "A payment attempt already exists. Check its status before continuing."
        )
    if task.status != "awaiting_payment":
        raise HTTPException(409, "Select a winning bid before paying")
    check_deadline(task)
    require_bookable_agent(db.get(Agent, task.winner_id))
    user = db.get(User, user_id)
    if get_settings().app_mode == "aws":
        from app.wallets import authorize_wallet_owner, validate_wallet_binding

        settings = authorize_wallet_owner(user)
        validate_wallet_binding(user, settings)
    bid = db.scalar(
        select(Bid).where(Bid.task_id == task.id, Bid.agent_id == task.winner_id)
    )
    amount = bid.price_micros
    claimed = db.execute(
        update(Task)
        .where(Task.id == task.id, Task.status == "awaiting_payment")
        .values(status="paying")
    )
    if not claimed.rowcount:
        db.rollback()
        raise HTTPException(409, "A payment is already in progress")
    from app.wallets import delegated_payment_limit

    limit = delegated_payment_limit(user_id)
    allowance = (
        [User.spent_micros + User.reserved_micros + amount <= limit]
        if limit is not None else []
    )
    reserved = db.execute(
        update(User)
        .where(
            User.id == user_id,
            User.budget_micros - User.spent_micros - User.reserved_micros >= amount,
            *allowance,
        )
        .values(reserved_micros=User.reserved_micros + amount)
    )
    if not reserved.rowcount:
        db.rollback()
        raise HTTPException(422, "This payment exceeds your remaining spending limit")
    payment = Payment(
        task_id=task.id,
        owner_id=user_id,
        agent_id=task.winner_id,
        amount_micros=amount,
        provider="demo" if get_settings().app_mode == "demo" else "agentcore",
        payer_user_id=user.payment_user_id,
        instrument_id=user.payment_instrument_id,
    )
    db.add(payment)
    db.commit()
    db.refresh(user)
    try:
        receipt = settle_payment(
            payment, user, db.get(Agent, task.winner_id), task, db.commit
        )
    except PaymentUncertain as exc:
        payment.status, payment.error, task.status = (
            "review_required",
            str(exc),
            "payment_review",
        )
        record(
            db,
            user_id,
            "payment_review",
            "Payment requires settlement reconciliation",
            task.id,
        )
        db.commit()
        raise HTTPException(409, str(exc)) from None
    except Exception:
        payment.status, payment.error, task.status = (
            "failed",
            "Payment setup failed before signing.",
            "payment_failed",
        )
        db.execute(
            update(User)
            .where(User.id == user_id)
            .values(reserved_micros=User.reserved_micros - amount)
        )
        record(db, user_id, "payment_failed", payment.error, task.id)
        db.commit()
        raise HTTPException(
            502, "Payment setup failed. No settlement was attempted."
        ) from None
    payment.status = "settled"
    payment.process_id, payment.session_id = (
        receipt["process_id"],
        receipt["session_id"],
    )
    payment.transaction_hash = receipt["transaction_hash"]
    task.status = "paid"
    db.execute(
        update(User)
        .where(User.id == user_id)
        .values(
            reserved_micros=User.reserved_micros - amount,
            spent_micros=User.spent_micros + amount,
        )
    )
    record(
        db, user_id, "payment_settled", f"{money(amount)} USDC payment settled", task.id
    )
    db.commit()
    return task_view(task, db)


def settle_marketplace(db, user_id, task_id):
    task = owned_task(db, task_id, user_id)
    if task.status == "completed":
        return task_view(task, db)
    agent = db.get(Agent, task.winner_id) if task.winner_id else None
    demo = bool(agent and is_demo_profile(agent))
    ready_status = "demo_ready" if demo else "paid"
    if task.status != ready_status:
        if demo:
            raise HTTPException(409, "Select a demo bid before starting delivery.")
        raise HTTPException(409, "A confirmed payment is required before delivery")
    transition(db, task, [ready_status], "delivering")
    try:
        result = call_bidders(
            {
                "action": "deliver",
                "agent": agent_view(agent),
                "task": {
                    "title": task.title,
                    "spec": task.spec,
                    "category": task.category,
                },
            }
        )
        if (
            not isinstance(result.get("delivery"), str)
            or not result["delivery"].strip()
        ):
            raise ValueError("Empty delivery")
        prefix = "> Demo deliverable · No payment was made.\n\n" if demo else ""
        task.delivery, task.status = prefix + result["delivery"][:100000], "completed"
        if not demo:
            db.execute(
                update(Agent)
                .where(Agent.id == agent.id)
                .values(completed_tasks=Agent.completed_tasks + 1)
            )
        record(
            db,
            user_id,
            "demo_delivered" if demo else "delivered",
            f'{agent.name} delivered "{task.title}"' + (" · Free demo" if demo else ""),
            task.id,
        )
        db.commit()
    except Exception:
        db.rollback()
        task = db.get(Task, task_id)
        task.status = ready_status
        db.commit()
        raise HTTPException(
            502, "Delivery failed. Retry delivery without paying again."
        ) from None
    return task_view(task, db)


def rate_task(db, user_id, task_id, data):
    score = Rating.model_validate(data).score
    task = owned_task(db, task_id, user_id)
    result = db.execute(
        update(Task)
        .where(Task.id == task.id, Task.status == "completed", Task.rating.is_(None))
        .values(rating=score)
    )
    if not result.rowcount:
        raise HTTPException(409, "Only completed, unrated tasks can be reviewed")
    demo = is_demo_profile(db.get(Agent, task.winner_id))
    if not demo:
        db.execute(
            update(Agent)
            .where(Agent.id == task.winner_id)
            .values(
                reputation_total=Agent.reputation_total + score,
                reputation_count=Agent.reputation_count + 1,
            )
        )
    record(
        db,
        user_id,
        "demo_feedback" if demo else "review_added",
        f"{'Demo feedback' if demo else 'Verified task review'}: {score}/5",
        task.id,
    )
    db.commit()
    db.refresh(task)
    return task_view(task, db)


def publish_agent(db, user_id, data):
    from sqlalchemy.exc import IntegrityError

    body = AgentCreate.model_validate(data)
    agent = Agent(
        owner_id=user_id,
        name=body.name,
        tagline=body.tagline,
        description=body.description,
        category=body.category,
        skills=body.skills,
        price_micros=micros(body.price),
        wallet=body.wallet,
        color="orange",
        icon="sparkles",
    )
    db.add(agent)
    record(db, user_id, "agent_published", f"Published {body.name}")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An agent with this wallet already exists") from None
    return agent_view(agent)


def update_budget(db, user_id, data):
    budget = micros(BudgetUpdate.model_validate(data).budget)
    from app.wallets import delegated_payment_limit

    limit = delegated_payment_limit(user_id)
    if limit is not None and budget > limit:
        raise HTTPException(
            422, f"Your shared-wallet allowance is capped at {money(limit)} USDC."
        )
    result = db.execute(
        update(User)
        .where(User.id == user_id, User.spent_micros + User.reserved_micros <= budget)
        .values(budget_micros=budget)
    )
    if not result.rowcount:
        raise HTTPException(
            422, "The spending limit cannot be lower than spent and reserved funds"
        )
    record(
        db, user_id, "budget_updated", f"Spending limit updated to {money(budget)} USDC"
    )
    db.commit()
    return {"budget": money(budget)}


def dispatch(db, user_id, action, data, task_id=None):
    operations = {
        "create_task": lambda: create_task(db, user_id, data),
        "quote_marketplace": lambda: quote_marketplace(db, user_id, task_id),
        "select_bid": lambda: select_bid(db, user_id, task_id, data),
        "auto_select_bid": lambda: auto_select_bid(db, user_id, task_id),
        "process_payment": lambda: process_payment(db, user_id, task_id),
        "settle_marketplace": lambda: settle_marketplace(db, user_id, task_id),
        "rate_task": lambda: rate_task(db, user_id, task_id, data),
        "publish_agent": lambda: publish_agent(db, user_id, data),
        "update_budget": lambda: update_budget(db, user_id, data),
    }
    if action not in operations:
        raise HTTPException(400, "Unknown marketplace action")
    if not db.get(User, user_id):
        raise HTTPException(401, "Unknown marketplace user")
    return operations[action]()
