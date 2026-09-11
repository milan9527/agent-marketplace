from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def uid() -> str:
    return str(uuid4())


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="Marketplace Builder")
    budget_micros: Mapped[int] = mapped_column(Integer, default=10_000_000)
    spent_micros: Mapped[int] = mapped_column(Integer, default=0)
    reserved_micros: Mapped[int] = mapped_column(Integer, default=0)
    payment_instrument_id: Mapped[str | None] = mapped_column(String(100))
    payment_user_id: Mapped[str | None] = mapped_column(String(120))
    payment_connector_id: Mapped[str | None] = mapped_column(String(211))
    wallet_address: Mapped[str | None] = mapped_column(String(42))
    wallet_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40), default=now)
    __table_args__ = (
        CheckConstraint(
            "budget_micros >= 0 AND spent_micros >= 0 AND reserved_micros >= 0"
        ),
    )


class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    tagline: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(40), index=True)
    skills: Mapped[list] = mapped_column(JSON)
    price_micros: Mapped[int] = mapped_column(Integer)
    wallet: Mapped[str] = mapped_column(String(42), unique=True)
    color: Mapped[str] = mapped_column(String(20), default="orange")
    icon: Mapped[str] = mapped_column(String(30), default="sparkles")
    featured: Mapped[bool] = mapped_column(default=False)
    active: Mapped[bool] = mapped_column(default=True)
    reputation_total: Mapped[int] = mapped_column(Integer, default=0)
    reputation_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_tasks: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(40), default=now)
    __table_args__ = (CheckConstraint("price_micros > 0"),)


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    spec: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(40))
    budget_micros: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    selection_mode: Mapped[str] = mapped_column(
        String(10), default="manual", server_default="manual"
    )
    agent_scope: Mapped[str] = mapped_column(
        String(10), default="all", server_default="all"
    )
    selection_reason: Mapped[str | None] = mapped_column(Text)
    preferred_agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"))
    winner_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"))
    delivery: Mapped[str | None] = mapped_column(Text)
    rating: Mapped[int | None] = mapped_column(Integer)
    deadline: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[str] = mapped_column(String(40), default=now)
    __table_args__ = (CheckConstraint("budget_micros > 0"),)


class Bid(Base):
    __tablename__ = "bids"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    price_micros: Mapped[int] = mapped_column(Integer)
    match_score: Mapped[int] = mapped_column(Integer)
    quality_score: Mapped[int] = mapped_column(Integer)
    rationale: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40), default=now)
    __table_args__ = (
        UniqueConstraint("task_id", "agent_id"),
        CheckConstraint("price_micros > 0"),
    )


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), unique=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    amount_micros: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    provider: Mapped[str] = mapped_column(String(30))
    session_id: Mapped[str | None] = mapped_column(String(100))
    process_id: Mapped[str | None] = mapped_column(String(100))
    payer_user_id: Mapped[str | None] = mapped_column(String(120))
    instrument_id: Mapped[str | None] = mapped_column(String(100))
    # Signed bearer proof is intentionally never persisted or returned to the browser.
    transaction_hash: Mapped[str | None] = mapped_column(String(100))
    error: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[str] = mapped_column(String(40), default=now)
    __table_args__ = (CheckConstraint("amount_micros > 0"),)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"))
    kind: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40), default=now)
    __table_args__ = (Index("ix_events_owner_created", "owner_id", "created_at"),)
