"""Add auto-apply criteria to discount codes.

Revision ID: cba9d4e5f6a1
Revises: b1c5699834a0
Create Date: 2026-08-15 03:10:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "cba9d4e5f6a1"
down_revision = "b1c5699834a0"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("discount_codes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("auto_apply", sa.Boolean(), nullable=False, server_default=sa.text("false")))
        batch_op.add_column(sa.Column("auto_apply_criteria", sa.JSON(), nullable=True, server_default=sa.text("'{}'")))


def downgrade():
    with op.batch_alter_table("discount_codes", schema=None) as batch_op:
        batch_op.drop_column("auto_apply_criteria")
        batch_op.drop_column("auto_apply")
