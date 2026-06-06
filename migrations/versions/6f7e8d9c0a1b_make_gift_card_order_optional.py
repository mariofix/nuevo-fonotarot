"""make gift_card.order_id nullable for admin-issued cards

Revision ID: 6f7e8d9c0a1b
Revises: 8591bbe22224
Create Date: 2026-06-04 23:01:00.000000

"""

from alembic import op
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "6f7e8d9c0a1b"
down_revision = "8591bbe22224"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("gift_cards", schema=None) as batch_op:
        batch_op.alter_column(
            "order_id",
            existing_type=mysql.INTEGER(),
            nullable=True,
        )


def downgrade():
    with op.batch_alter_table("gift_cards", schema=None) as batch_op:
        batch_op.alter_column(
            "order_id",
            existing_type=mysql.INTEGER(),
            nullable=False,
        )
