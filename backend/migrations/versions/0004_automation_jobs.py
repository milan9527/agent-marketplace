"""Persist explicit authorization and progress for automatic task execution."""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "automation_jobs",
        sa.Column(
            "task_id", sa.String(36), sa.ForeignKey("tasks.id"), primary_key=True
        ),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("stage", sa.String(30), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.Integer(), nullable=False),
        sa.Column("lease_until", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.String(36), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
    )
    op.create_index(
        "ix_automation_ready", "automation_jobs", ["status", "available_at"]
    )


def downgrade():
    op.drop_index("ix_automation_ready", table_name="automation_jobs")
    op.drop_table("automation_jobs")
