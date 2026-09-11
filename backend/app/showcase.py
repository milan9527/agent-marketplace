"""Explicit read-only sharing of selected test records with one demo account."""

from fastapi import HTTPException
from sqlalchemy import or_, select

from app.config import get_settings
from app.models import Task
from app.service import task_view


def shared_ids(user, resource):
    settings = get_settings()
    if not settings.showcase_user_sub or user.id != settings.showcase_user_sub:
        return ()
    configured = getattr(settings, f"showcase_{resource}_ids")
    return tuple(value.strip() for value in configured.split(",") if value.strip())


def task_visibility(user):
    return or_(Task.owner_id == user.id, Task.id.in_(shared_ids(user, "task")))


def readable_task(db, task_id, user):
    task = db.scalar(select(Task).where(Task.id == task_id, task_visibility(user)))
    if task is None:
        raise HTTPException(404, "Task not found")
    return task


def visible_task_view(task, db, user):
    result = task_view(task, db)
    result["read_only"] = task.owner_id != user.id
    if result["payment"]:
        result["payment"]["read_only"] = result["read_only"]
    return result
