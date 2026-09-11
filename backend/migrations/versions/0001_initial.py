"""Initial marketplace schema."""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("budget_micros", sa.Integer, nullable=False),
        sa.Column("spent_micros", sa.Integer, nullable=False),
        sa.Column("reserved_micros", sa.Integer, nullable=False),
        sa.Column("payment_instrument_id", sa.String(100)),
        sa.Column("wallet_url", sa.Text),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.CheckConstraint(
            "budget_micros >= 0 AND spent_micros >= 0 AND reserved_micros >= 0"
        ),
    )
    op.create_table(
        "agents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "owner_id", sa.String(128), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("tagline", sa.String(180), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("skills", sa.JSON, nullable=False),
        sa.Column("price_micros", sa.Integer, nullable=False),
        sa.Column("wallet", sa.String(42), nullable=False, unique=True),
        sa.Column("color", sa.String(20), nullable=False),
        sa.Column("icon", sa.String(30), nullable=False),
        sa.Column("featured", sa.Boolean, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False),
        sa.Column("reputation_total", sa.Integer, nullable=False),
        sa.Column("reputation_count", sa.Integer, nullable=False),
        sa.Column("completed_tasks", sa.Integer, nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.CheckConstraint("price_micros > 0"),
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "owner_id", sa.String(128), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("spec", sa.Text, nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("budget_micros", sa.Integer, nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("preferred_agent_id", sa.String(36), sa.ForeignKey("agents.id")),
        sa.Column("winner_id", sa.String(36), sa.ForeignKey("agents.id")),
        sa.Column("delivery", sa.Text),
        sa.Column("rating", sa.Integer),
        sa.Column("deadline", sa.String(40), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.CheckConstraint("budget_micros > 0"),
    )
    op.create_table(
        "bids",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column(
            "agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=False
        ),
        sa.Column("price_micros", sa.Integer, nullable=False),
        sa.Column("match_score", sa.Integer, nullable=False),
        sa.Column("quality_score", sa.Integer, nullable=False),
        sa.Column("rationale", sa.Text, nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("task_id", "agent_id"),
        sa.CheckConstraint("price_micros > 0"),
    )
    op.create_table(
        "payments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "task_id",
            sa.String(36),
            sa.ForeignKey("tasks.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "owner_id", sa.String(128), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=False
        ),
        sa.Column("amount_micros", sa.Integer, nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("session_id", sa.String(100)),
        sa.Column("process_id", sa.String(100)),
        sa.Column("transaction_hash", sa.String(100)),
        sa.Column("error", sa.String(300)),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.CheckConstraint("amount_micros > 0"),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "owner_id", sa.String(128), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id")),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    for table, columns in {
        "agents": ["owner_id", "category"],
        "tasks": ["owner_id", "status"],
        "bids": ["task_id"],
        "payments": ["owner_id"],
    }.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])
    op.create_index("ix_events_owner_created", "events", ["owner_id", "created_at"])


def downgrade():
    for table in ("events", "payments", "bids", "tasks", "agents", "users"):
        op.drop_table(table)
