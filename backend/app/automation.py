"""Durable, explicitly authorized workflows; each lease advances one stage."""

import logging
import time

from fastapi import HTTPException
from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.models import AutomationJob, Payment, Task, now, uid
from app.service import (
    auto_select_bid,
    check_deadline,
    owned_task,
    process_payment,
    quote_marketplace,
    record,
    settle_marketplace,
    task_view,
)

LEASE_SECONDS = 600
IN_PROGRESS = {"quoting", "paying", "delivering"}
SAFE_STATES = {"open", "bidding", "awaiting_payment", "demo_ready", "paid", "executing"}


def start_automation(db, user_id, task_id):
    # Lock the task so two concurrent authorization requests create one job.
    task = db.scalar(
        select(Task)
        .where(
            Task.id == task_id,
            Task.owner_id == user_id,
        )
        .with_for_update()
    )
    if not task:
        raise HTTPException(404, "Task not found")
    job = db.get(AutomationJob, task.id)
    if job and job.status in {"queued", "running", "completed"}:
        return task_view(task, db)
    if task.status not in SAFE_STATES:
        raise HTTPException(
            409, "This task cannot start automatically. Check its current status."
        )
    if task.status not in {"paid", "demo_ready", "executing"}:
        check_deadline(task)
    payment = db.scalar(select(Payment).where(Payment.task_id == task.id))
    if payment and payment.status != "settled":
        raise HTTPException(
            409, "An existing payment must be reconciled before continuing."
        )
    if job is None:
        job = AutomationJob(task_id=task.id)
        db.add(job)
    job.status, job.stage, job.error = "queued", task.status, None
    job.attempts, job.available_at, job.lease_until = 0, 0, 0
    job.lease_token, job.updated_at = None, now()
    task.selection_mode = "auto"
    record(
        db,
        user_id,
        "automation_authorized",
        "Authorized automatic bidding, selection, payment within the task budget, and delivery.",
        task.id,
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.get(AutomationJob, task_id)
        if not existing:
            raise
    return task_view(task, db)


def _finish(db, task_id, token, status, error=None, attempts=0, delay=0):
    db.expire_all()
    task = db.get(Task, task_id)
    changed = db.execute(
        update(AutomationJob)
        .where(
            AutomationJob.task_id == task_id,
            AutomationJob.lease_token == token,
        )
        .values(
            status=status,
            stage=task.status,
            error=error,
            attempts=attempts,
            available_at=int(time.time()) + delay,
            lease_until=0,
            lease_token=None,
            updated_at=now(),
        )
    )
    if changed.rowcount and status in {"blocked", "review_required", "completed"}:
        record(
            db,
            task.owner_id,
            "automation_" + status,
            error or "Automatic task completed.",
            task.id,
        )
    db.commit()
    return {
        "processed": True,
        "task_id": task_id,
        "status": status,
        "stage": task.status,
    }


def ready_jobs(timestamp):
    return or_(
        and_(AutomationJob.status == "queued", AutomationJob.available_at <= timestamp),
        and_(AutomationJob.status == "running", AutomationJob.lease_until <= timestamp),
    )


def has_ready_job(db):
    return (
        db.scalar(
            select(AutomationJob.task_id)
            .where(
                ready_jobs(int(time.time())),
            )
            .limit(1)
        )
        is not None
    )


def advance_automation(db):
    """Internal Runtime operation. The job supplies its owner, never the caller."""
    timestamp = int(time.time())
    ready = ready_jobs(timestamp)
    job = db.scalar(
        select(AutomationJob)
        .where(ready)
        .order_by(
            AutomationJob.available_at,
            AutomationJob.created_at,
        )
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if not job:
        db.rollback()
        return {"processed": False}
    task_id, attempts = job.task_id, job.attempts
    token = uid()
    claimed = db.execute(
        update(AutomationJob)
        .where(
            AutomationJob.task_id == task_id,
            ready,
        )
        .values(
            status="running", lease_token=token, lease_until=timestamp + LEASE_SECONDS
        )
    )
    if not claimed.rowcount:
        db.rollback()
        return {"processed": False}
    db.commit()
    db.expire_all()
    task = db.get(Task, task_id)
    initial_stage = task.status
    if task.status == "completed":
        return _finish(db, task_id, token, "completed")
    if task.status in IN_PROGRESS:
        # A lost worker's operation may have reached the provider. Never reset
        # it or issue a replacement payment just because a lease expired.
        return _finish(
            db,
            task_id,
            token,
            "review_required" if task.status == "paying" else "blocked",
            "An earlier operation did not confirm completion. An operator must check its result before continuing.",
        )
    try:
        owned_task(db, task_id, task.owner_id)
        if task.status == "open":
            quote_marketplace(db, task.owner_id, task_id)
        elif task.status == "bidding":
            auto_select_bid(db, task.owner_id, task_id)
        elif task.status == "awaiting_payment":
            process_payment(db, task.owner_id, task_id)
        elif task.status in {"paid", "demo_ready", "executing"}:
            settle_marketplace(db, task.owner_id, task_id, job_lease_token=token)
        else:
            return _finish(
                db,
                task_id,
                token,
                "review_required" if task.status == "payment_review" else "blocked",
                "Check this task's payment status before continuing.",
            )
    except Exception as exc:
        db.rollback()
        db.expire_all()
        task = db.get(Task, task_id)
        if task.status == "completed":
            return _finish(db, task_id, token, "completed")
        message = (
            str(exc.detail)
            if isinstance(exc, HTTPException)
            else "The automatic workflow could not complete this step."
        )
        logging.getLogger("automation").warning(
            "Workflow step stopped: task=%s state=%s error=%s",
            task_id,
            task.status,
            type(exc).__name__,
        )
        if task.status in {"paying", "payment_review"}:
            return _finish(db, task_id, token, "review_required", message)
        # Retrying bidding or delivery is safe after the service restored its
        # ready state. No payment attempts are retried by this worker.
        if (
            isinstance(exc, HTTPException)
            and exc.status_code >= 500
            and task.status in {"open", "paid", "demo_ready", "executing"}
            and attempts < 2
        ):
            return _finish(
                db,
                task_id,
                token,
                "queued",
                message,
                attempts=attempts + 1,
                delay=5 * (attempts + 1),
            )
        return _finish(db, task_id, token, "blocked", message, attempts=attempts + 1)
    db.expire_all()
    task = db.get(Task, task_id)
    if task.status == "bidding" and not task.winner_id:
        return _finish(db, task_id, token, "blocked", task.selection_reason)
    if task.status == "execution_blocked":
        from app.execution_service import latest_run

        run = latest_run(db, task.id)
        return _finish(db, task_id, token, "blocked", run.state.get("error"))
    if task.status == initial_stage and task.status != "executing":
        return _finish(
            db,
            task_id,
            token,
            "blocked",
            "This step did not advance. Check the task and payment status before continuing.",
        )
    return _finish(
        db,
        task_id,
        token,
        "completed" if task.status == "completed" else "queued",
    )
