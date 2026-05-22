"""add digital gift card products and issued codes

Revision ID: a7b8c9d0e1f2
Revises: f7a1b2c3d4e5
Create Date: 2026-05-21 22:08:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a7b8c9d0e1f2"
down_revision = "f7a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gift_card_products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("image_url", sa.String(length=500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_featured", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("gift_card_products", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_gift_card_products_slug"), ["slug"], unique=True)

    op.create_table(
        "gift_cards",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("gift_card_product_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("purchaser_email", sa.String(length=255), nullable=True),
        sa.Column("recipient_email", sa.String(length=255), nullable=True),
        sa.Column("redeemed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("redeemed_at", sa.DateTime(), nullable=True),
        sa.Column("redemption_order_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["gift_card_product_id"], ["gift_card_products.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["redeemed_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("gift_cards", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_gift_cards_code"), ["code"], unique=True)
        batch_op.create_index(batch_op.f("ix_gift_cards_order_id"), ["order_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_gift_cards_redeemed_by_user_id"), ["redeemed_by_user_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("gift_cards", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_gift_cards_redeemed_by_user_id"))
        batch_op.drop_index(batch_op.f("ix_gift_cards_order_id"))
        batch_op.drop_index(batch_op.f("ix_gift_cards_code"))
    op.drop_table("gift_cards")

    with op.batch_alter_table("gift_card_products", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_gift_card_products_slug"))
    op.drop_table("gift_card_products")
