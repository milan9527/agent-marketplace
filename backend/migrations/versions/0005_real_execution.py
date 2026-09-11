"""Persist requirements and real tool execution evidence, without enrolling old tasks."""

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tasks", sa.Column("requirements", sa.JSON(), nullable=True))
    op.create_table(
        "execution_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("original_delivery", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
    )
    op.create_index(
        "ix_execution_task_created", "execution_runs", ["task_id", "created_at"]
    )


def downgrade():
    op.drop_index("ix_execution_task_created", table_name="execution_runs")
    op.drop_table("execution_runs")
    op.drop_column("tasks", "requirements")
