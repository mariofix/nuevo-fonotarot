"""add favorite tarotista and notification preferences

Revision ID: 0a1b2c3d4e5f
Revises: b57d52cba819
Create Date: 2026-05-19 22:35:04.140000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0a1b2c3d4e5f"
down_revision = "b57d52cba819"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("favorite_tarotista_option", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "notification_preferences",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "notification_preferences")
    op.drop_column("users", "favorite_tarotista_option")
