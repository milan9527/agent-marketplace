"""Reuse an existing Stripe/Privy instrument with an explicit owner mapping."""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("payment_user_id", sa.String(120)))
    op.add_column("users", sa.Column("payment_connector_id", sa.String(211)))
    op.add_column("users", sa.Column("wallet_address", sa.String(42)))
    op.add_column("payments", sa.Column("payer_user_id", sa.String(120)))
    op.add_column("payments", sa.Column("instrument_id", sa.String(100)))


def downgrade():
    for column in ("instrument_id", "payer_user_id"):
        op.drop_column("payments", column)
    for column in ("wallet_address", "payment_connector_id", "payment_user_id"):
        op.drop_column("users", column)
