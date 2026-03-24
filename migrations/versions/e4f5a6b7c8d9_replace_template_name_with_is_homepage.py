"""replace template_name with is_homepage on static_pages

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-03-24

"""
from alembic import op
import sqlalchemy as sa

revision = 'e4f5a6b7c8d9'
down_revision = 'd3e4f5a6b7c8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('static_pages', sa.Column('is_homepage', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.drop_column('static_pages', 'template_name')


def downgrade():
    op.add_column('static_pages', sa.Column('template_name', sa.String(255), nullable=True))
    op.drop_column('static_pages', 'is_homepage')
