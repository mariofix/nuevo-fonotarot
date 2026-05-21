"""add featured_image_url to static_pages

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-03-24

"""

import sqlalchemy as sa
from alembic import op

revision = "d3e4f5a6b7c8"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("static_pages", sa.Column("featured_image_url", sa.String(500), nullable=True))


def downgrade():
    op.drop_column("static_pages", "featured_image_url")
