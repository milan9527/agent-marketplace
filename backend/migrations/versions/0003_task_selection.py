"""Persist task selection preferences and the winning decision."""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "tasks",
        sa.Column(
            "selection_mode", sa.String(10), nullable=False, server_default="manual"
        ),
    )
    op.add_column(
        "tasks",
        sa.Column("agent_scope", sa.String(10), nullable=False, server_default="all"),
    )
    op.add_column("tasks", sa.Column("selection_reason", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("tasks", "selection_reason")
    op.drop_column("tasks", "agent_scope")
    op.drop_column("tasks", "selection_mode")
