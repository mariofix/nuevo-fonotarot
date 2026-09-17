"""add minute pack role prices

Revision ID: d9f8e7c6b5a4
Revises: b1c5699834a0
Create Date: 2026-09-17 04:05:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d9f8e7c6b5a4"
down_revision = "b1c5699834a0"
branch_labels = None
depends_on = None


LOYALTY_ROLE_NAMES = ("leales-oro", "leales-plata", "leales-bronze")


def upgrade():
    op.create_table(
        "minute_pack_role_prices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("minute_pack_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="CLP"),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["minute_pack_id"], ["minute_packs.id"]),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "minute_pack_id",
            "role_id",
            "starts_at",
            name="uq_minute_pack_role_prices_pack_role_start",
        ),
    )
    with op.batch_alter_table("minute_pack_role_prices", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_minute_pack_role_prices_minute_pack_id"), ["minute_pack_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_minute_pack_role_prices_role_id"), ["role_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_minute_pack_role_prices_starts_at"), ["starts_at"], unique=False)

    roles_table = sa.table(
        "roles",
        sa.column("name", sa.String(length=80)),
        sa.column("description", sa.String(length=255)),
    )
    bind = op.get_bind()
    for role_name in LOYALTY_ROLE_NAMES:
        exists = bind.execute(
            sa.select(sa.literal(1)).select_from(roles_table).where(roles_table.c.name == role_name),
        ).scalar()
        if exists:
            continue
        op.bulk_insert(
            roles_table,
            [
                {
                    "name": role_name,
                    "description": "Rol de clientes leales para precios preferenciales.",
                }
            ],
        )


def downgrade():
    with op.batch_alter_table("minute_pack_role_prices", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_minute_pack_role_prices_starts_at"))
        batch_op.drop_index(batch_op.f("ix_minute_pack_role_prices_role_id"))
        batch_op.drop_index(batch_op.f("ix_minute_pack_role_prices_minute_pack_id"))

    op.drop_table("minute_pack_role_prices")
