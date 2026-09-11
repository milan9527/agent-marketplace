"""Persist tool turns and expose evidence without exposing model conversation state."""

import time

from fastapi import HTTPException
from sqlalchemy import select, update

from app.models import Agent, AutomationJob, ExecutionRun, Payment, Task, now, uid
from app.seed import is_demo_profile


def latest_run(db, task_id):
    return db.scalar(
        select(ExecutionRun)
        .where(ExecutionRun.task_id == task_id)
        .order_by(ExecutionRun.created_at.desc(), ExecutionRun.id.desc())
        .limit(1)
    )


def execution_view(run):
    if run is None:
        return None
    state = run.state
    return {
        "id": run.id,
        "status": run.status,
        "started_at": run.created_at,
        "updated_at": run.updated_at,
        "steps": state.get("steps", 0),
        "error": state.get("error"),
        "requirements": state.get("requirements"),
        "trace": state.get("trace", []),
        "sources": [
            {k: v for k, v in source.items() if k not in {"text", "snippet"}}
            for source in state.get("sources", [])
        ],
        "artifacts": [
            {k: v for k, v in item.items() if k != "content"}
            for item in state.get("artifacts", [])
        ],
        "validation": state.get("validation"),
        "has_previous_delivery": bool(run.original_delivery),
    }


def queue_delivery(db, task):
    from app.automation import LEASE_SECONDS

    job = db.get(AutomationJob, task.id)
    if not job:
        job = AutomationJob(task_id=task.id)
        db.add(job)
    token = uid()
    job.status, job.stage = "running", task.status
    job.lease_token, job.lease_until = token, int(time.time()) + LEASE_SECONDS
    job.error, job.updated_at, job.attempts = None, now(), 0
    return token


def release_manual_delivery(db, task, token, error=None):
    if not token:
        return
    status = (
        "completed"
        if task.status == "completed"
        else "blocked"
        if task.status == "execution_blocked"
        else "queued"
    )
    db.execute(
        update(AutomationJob)
        .where(AutomationJob.task_id == task.id, AutomationJob.lease_token == token)
        .values(
            status=status,
            stage=task.status,
            error=error,
            lease_token=None,
            lease_until=0,
            available_at=int(time.time()),
            updated_at=now(),
        )
    )


def advance_execution(db, user_id, task_id, *, job_lease_token=None):
    from app.agents import call_bidders
    from app.service import owned_task, record, task_view, transition

    task = owned_task(db, task_id, user_id)
    if task.status == "completed":
        return task_view(task, db)
    job = db.get(AutomationJob, task.id)
    if job_lease_token is None and job and job.status in {"queued", "running"}:
        # A repeated API request observes the existing work, including an in-flight turn.
        return task_view(task, db)
    agent = db.get(Agent, task.winner_id) if task.winner_id else None
    demo = bool(agent and is_demo_profile(agent))
    if task.status not in {"demo_ready" if demo else "paid", "executing"}:
        raise HTTPException(
            409, "Select an agent and confirm any required payment before execution."
        )
    if not demo:
        payment = db.scalar(select(Payment).where(Payment.task_id == task.id))
        if not payment or payment.status != "settled":
            raise HTTPException(409, "Confirmed payment is required before execution.")
    if job_lease_token is not None:
        if (
            not job
            or job.status != "running"
            or job.lease_token != job_lease_token
            or job.lease_until <= time.time()
        ):
            raise HTTPException(409, "This worker no longer owns the execution lease.")
    ready = task.status
    transition(db, task, [ready], "delivering")
    run = latest_run(db, task.id)
    if not run or run.status not in {"running", "validating"}:
        run = ExecutionRun(task_id=task.id, state={})
        db.add(run)
        db.flush()
        record(
            db, user_id, "execution_started", "Started real tool execution.", task.id
        )
    manual_token = queue_delivery(db, task) if job_lease_token is None else None
    db.commit()
    previous_trace = len(run.state.get("trace", []))
    try:
        from app.service import agent_view

        result = call_bidders(
            {
                "action": "execute_step",
                "task_id": task.id,
                "agent": agent_view(agent),
                "task": {
                    "title": task.title,
                    "spec": task.spec,
                    "category": task.category,
                },
                "requirements": task.requirements,
                "execution_state": run.state,
            }
        )
        state = result["execution_state"]
        if state.get("status") not in {"running", "validating", "completed", "blocked"}:
            raise ValueError("Invalid execution state")
        run.state, run.status, run.updated_at = state, state["status"], now()
        for trace in state.get("trace", [])[previous_trace:]:
            record(
                db,
                user_id,
                "tool_" + trace["status"],
                f"{trace['tool']}: {trace['status']}",
                task.id,
            )
        if run.status == "completed":
            if (
                not state.get("report")
                or state.get("validation", {}).get("passed") is not True
            ):
                raise ValueError("Execution has no validated deliverable")
            prefix = "> Free agent execution · No payment was made.\n\n" if demo else ""
            task.delivery, task.status = prefix + state["report"], "completed"
            if not demo and not run.original_delivery:
                db.execute(
                    update(Agent)
                    .where(Agent.id == agent.id)
                    .values(completed_tasks=Agent.completed_tasks + 1)
                )
            record(
                db,
                user_id,
                "execution_completed",
                "Tools executed and the deliverable passed evidence checks.",
                task.id,
            )
        elif run.status == "blocked":
            task.status = "execution_blocked"
            record(
                db,
                user_id,
                "execution_blocked",
                state.get("error", "Execution could not satisfy the task."),
                task.id,
            )
        else:
            task.status = "executing"
        release_manual_delivery(db, task, manual_token, state.get("error"))
        db.commit()
    except Exception:
        db.rollback()
        task = db.get(Task, task_id)
        task.status = "executing"
        release_manual_delivery(db, task, manual_token)
        db.commit()
        raise HTTPException(
            502,
            "Execution step failed. Progress is saved; retry does not charge again.",
        ) from None
    return task_view(task, db)


def rerun_execution(db, user_id, task_id):
    from app.service import owned_task, record, task_view

    task = owned_task(db, task_id, user_id)
    if task.status not in {"completed", "execution_blocked"}:
        raise HTTPException(
            409, "Only completed or blocked tasks can start a new execution."
        )
    agent = db.get(Agent, task.winner_id)
    if not agent:
        raise HTTPException(409, "The task has no selected agent.")
    if not is_demo_profile(agent):
        payment = db.scalar(select(Payment).where(Payment.task_id == task.id))
        if not payment or payment.status != "settled":
            raise HTTPException(
                409, "The original payment must be settled before rerunning."
            )
    # Lock the task before creating a new run; concurrent reruns cannot duplicate work.
    changed = db.execute(
        update(Task)
        .where(
            Task.id == task.id,
            Task.status == task.status,
        )
        .values(status="executing")
    )
    if not changed.rowcount:
        raise HTTPException(409, "Execution has already started.")
    old = latest_run(db, task.id)
    db.add(
        ExecutionRun(
            task_id=task.id,
            state={},
            original_delivery=task.delivery or (old.original_delivery if old else None),
        )
    )
    task.delivery = None
    # Re-assess capabilities instead of inheriting a historical text-only plan.
    task.requirements = None
    job = db.get(AutomationJob, task.id)
    if not job:
        job = AutomationJob(task_id=task.id)
        db.add(job)
    job.status, job.stage, job.error = "queued", "executing", None
    job.available_at, job.lease_until, job.attempts = 0, 0, 0
    job.lease_token, job.updated_at = None, now()
    record(
        db,
        user_id,
        "execution_authorized",
        "Authorized a new tool execution using the existing payment or free agent. No new payment.",
        task.id,
    )
    db.commit()
    return task_view(task, db)
