"""add order item fulfillment tracking

Revision ID: 1c2d3e4f5a6b
Revises: 8f4a6b9c2d10, 0a1b2c3d4e5f, 6f7e8d9c0a1b
Create Date: 2026-06-08 19:35:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "1c2d3e4f5a6b"
down_revision = ("8f4a6b9c2d10", "0a1b2c3d4e5f", "6f7e8d9c0a1b")
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("order_items", schema=None) as batch_op:
        batch_op.add_column(sa.Column("fulfillment_status", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("fulfilled_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("fulfillment_error", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("fulfillment_attempts", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("fulfillment_reference", sa.String(length=255), nullable=True))

    op.execute("UPDATE order_items SET fulfillment_status = 'pending' WHERE fulfillment_status IS NULL")
    op.execute("UPDATE order_items SET fulfillment_attempts = 0 WHERE fulfillment_attempts IS NULL")

    with op.batch_alter_table("order_items", schema=None) as batch_op:
        batch_op.alter_column("fulfillment_status", existing_type=sa.String(length=20), nullable=False)
        batch_op.alter_column("fulfillment_attempts", existing_type=sa.Integer(), nullable=False)


def downgrade():
    with op.batch_alter_table("order_items", schema=None) as batch_op:
        batch_op.drop_column("fulfillment_reference")
        batch_op.drop_column("fulfillment_attempts")
        batch_op.drop_column("fulfillment_error")
        batch_op.drop_column("fulfilled_at")
        batch_op.drop_column("fulfillment_status")
