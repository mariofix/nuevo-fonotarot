"""Merge Payment into Order: add PaymentMixin columns, drop fm_payments

Payment tracking is consolidated directly onto the orders table by mixing
PaymentMixin into the Order model.  The separate fm_payments table is removed.

Migration steps (upgrade):
1. Add PaymentMixin columns (merchants_id, transaction_id, provider, amount,
   currency, state, email, extra_args, request_payload, response_payload,
   payment_object) to the orders table.
2. Migrate existing data: orders.payment_token → transaction_id,
   orders.payment_method → provider.
3. Drop the now-redundant payment_method and payment_token columns.
4. Drop the fm_payments table (no longer used).

Revision ID: d1e2f3a4b5c6
Revises: 3fe44943e8c1
Create Date: 2026-03-15 01:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision = 'd1e2f3a4b5c6'
down_revision = '3fe44943e8c1'
branch_labels = None
depends_on = None


def upgrade():
    # ------------------------------------------------------------------
    # 1. Add PaymentMixin columns to orders (all nullable — payment is
    #    populated after the order is created).
    # ------------------------------------------------------------------
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'merchants_id', sa.String(length=128), nullable=True
        ))
        batch_op.add_column(sa.Column(
            'transaction_id', sa.String(length=128), nullable=True
        ))
        batch_op.add_column(sa.Column(
            'provider', sa.String(length=64), nullable=True
        ))
        batch_op.add_column(sa.Column(
            'amount', sa.Numeric(precision=19, scale=4), nullable=True
        ))
        batch_op.add_column(sa.Column(
            'currency', sa.String(length=3), nullable=True
        ))
        batch_op.add_column(sa.Column(
            'state', sa.String(length=32), nullable=True
        ))
        batch_op.add_column(sa.Column(
            'email', sa.String(length=255), nullable=True
        ))
        batch_op.add_column(sa.Column(
            'extra_args', sa.JSON(),
            server_default=sa.text("'{}'"), nullable=True
        ))
        batch_op.add_column(sa.Column(
            'request_payload', sa.JSON(),
            server_default=sa.text("'{}'"), nullable=True
        ))
        batch_op.add_column(sa.Column(
            'response_payload', sa.JSON(),
            server_default=sa.text("'{}'"), nullable=True
        ))
        batch_op.add_column(sa.Column(
            'payment_object', sa.JSON(),
            server_default=sa.text("'{}'"), nullable=True
        ))

    # ------------------------------------------------------------------
    # 2. Migrate existing data from the old columns to the new ones.
    # ------------------------------------------------------------------
    op.execute("""
        UPDATE orders
        SET transaction_id = payment_token,
            provider       = payment_method,
            state          = 'pending'
        WHERE payment_token IS NOT NULL
    """)

    # ------------------------------------------------------------------
    # 3. Create indexes on the new columns.
    # ------------------------------------------------------------------
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_orders_merchants_id'), ['merchants_id'], unique=True
        )
        batch_op.create_index(
            batch_op.f('ix_orders_transaction_id'), ['transaction_id'], unique=True
        )
        batch_op.create_index(
            batch_op.f('ix_orders_provider'), ['provider'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_orders_state'), ['state'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_orders_email'), ['email'], unique=False
        )

    # ------------------------------------------------------------------
    # 4. Remove the now-redundant legacy columns.
    # ------------------------------------------------------------------
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.drop_column('payment_method')
        batch_op.drop_column('payment_token')

    # ------------------------------------------------------------------
    # 5. Drop the fm_payments table (superseded by the merged Order model).
    # ------------------------------------------------------------------
    with op.batch_alter_table('fm_payments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_fm_payments_transaction_id'))
        batch_op.drop_index(batch_op.f('ix_fm_payments_state'))
        batch_op.drop_index(batch_op.f('ix_fm_payments_provider'))
        batch_op.drop_index(batch_op.f('ix_fm_payments_merchants_id'))
        batch_op.drop_index(batch_op.f('ix_fm_payments_email'))

    op.drop_table('fm_payments')


def downgrade():
    # ------------------------------------------------------------------
    # 1. Re-create the fm_payments table.
    # ------------------------------------------------------------------
    op.create_table(
        'fm_payments',
        sa.Column('id', sa.INTEGER(), nullable=False),
        sa.Column('merchants_id', sa.VARCHAR(length=128), nullable=False),
        sa.Column('transaction_id', sa.VARCHAR(length=128), nullable=False),
        sa.Column('provider', sa.VARCHAR(length=64), nullable=False),
        sa.Column('amount', sa.NUMERIC(precision=19, scale=4), nullable=False),
        sa.Column('currency', sa.VARCHAR(length=3), nullable=False),
        sa.Column('state', sa.VARCHAR(length=32), nullable=False),
        sa.Column('email', sa.VARCHAR(length=255), nullable=True),
        sa.Column('extra_args', sqlite.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column('request_payload', sqlite.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column('response_payload', sqlite.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column('payment_object', sqlite.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column('extra_data', sqlite.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column('created_at', sa.DATETIME(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DATETIME(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('fm_payments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_fm_payments_email'), ['email'], unique=False)
        batch_op.create_index(batch_op.f('ix_fm_payments_merchants_id'), ['merchants_id'], unique=True)
        batch_op.create_index(batch_op.f('ix_fm_payments_provider'), ['provider'], unique=False)
        batch_op.create_index(batch_op.f('ix_fm_payments_state'), ['state'], unique=False)
        batch_op.create_index(batch_op.f('ix_fm_payments_transaction_id'), ['transaction_id'], unique=True)

    # ------------------------------------------------------------------
    # 2. Restore legacy payment columns on orders.
    # ------------------------------------------------------------------
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'payment_method', sa.String(length=30), nullable=True
        ))
        batch_op.add_column(sa.Column(
            'payment_token', sa.String(length=255), nullable=True
        ))

    op.execute("""
        UPDATE orders
        SET payment_method = provider,
            payment_token  = transaction_id
        WHERE transaction_id IS NOT NULL
    """)

    # ------------------------------------------------------------------
    # 3. Drop indexes and PaymentMixin columns from orders.
    # ------------------------------------------------------------------
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_orders_email'))
        batch_op.drop_index(batch_op.f('ix_orders_state'))
        batch_op.drop_index(batch_op.f('ix_orders_provider'))
        batch_op.drop_index(batch_op.f('ix_orders_transaction_id'))
        batch_op.drop_index(batch_op.f('ix_orders_merchants_id'))
        batch_op.drop_column('payment_object')
        batch_op.drop_column('response_payload')
        batch_op.drop_column('request_payload')
        batch_op.drop_column('extra_args')
        batch_op.drop_column('email')
        batch_op.drop_column('state')
        batch_op.drop_column('currency')
        batch_op.drop_column('amount')
        batch_op.drop_column('provider')
        batch_op.drop_column('transaction_id')
        batch_op.drop_column('merchants_id')
