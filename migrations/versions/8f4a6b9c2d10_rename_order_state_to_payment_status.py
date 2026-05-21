"""rename orders.state to payment_status

Revision ID: 8f4a6b9c2d10
Revises: 8918248ea857
Create Date: 2026-05-18 23:20:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "8f4a6b9c2d10"
down_revision = "8918248ea857"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_orders_state"))
        batch_op.alter_column(
            "state",
            existing_type=sa.String(length=32),
            new_column_name="payment_status",
            existing_nullable=True,
        )
        batch_op.create_index(
            batch_op.f("ix_orders_payment_status"),
            ["payment_status"],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_orders_payment_status"))
        batch_op.alter_column(
            "payment_status",
            existing_type=sa.String(length=32),
            new_column_name="state",
            existing_nullable=True,
        )
        batch_op.create_index(batch_op.f("ix_orders_state"), ["state"], unique=False)
