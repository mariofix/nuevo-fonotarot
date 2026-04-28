"""add firenze_client_id to users and orders

Revision ID: a9b8c7d6e5f4
Revises: e4f5a6b7c8d9
Create Date: 2026-04-28 02:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a9b8c7d6e5f4'
down_revision = 'e4f5a6b7c8d9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('firenze_client_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_users_firenze_client_id'), 'users', ['firenze_client_id'], unique=False)

    op.add_column('orders', sa.Column('firenze_client_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_orders_firenze_client_id'), 'orders', ['firenze_client_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_orders_firenze_client_id'), table_name='orders')
    op.drop_column('orders', 'firenze_client_id')

    op.drop_index(op.f('ix_users_firenze_client_id'), table_name='users')
    op.drop_column('users', 'firenze_client_id')
