"""add images gallery column to products

Revision ID: f7a1b2c3d4e5
Revises: 9b8c7d6e5f4a
Create Date: 2026-05-21 21:53:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f7a1b2c3d4e5"
down_revision = "9b8c7d6e5f4a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("products", schema=None) as batch_op:
        batch_op.add_column(sa.Column("images", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("products", schema=None) as batch_op:
        batch_op.drop_column("images")
