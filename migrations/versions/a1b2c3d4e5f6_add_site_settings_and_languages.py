"""add site_settings and site_languages tables

Revision ID: a1b2c3d4e5f6
Revises: 260a0a1f4766
Create Date: 2026-02-25 08:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '260a0a1f4766'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'site_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=80), nullable=False),
        sa.Column('value', sa.Text(), nullable=True),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('module', sa.String(length=50), nullable=False, server_default='general'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_site_settings_key'), ['key'], unique=True)

    op.create_table(
        'site_languages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('locale', sa.String(length=10), nullable=False),
        sa.Column('flag_class', sa.String(length=50), nullable=False),
        sa.Column('label', sa.String(length=50), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('site_languages', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_site_languages_locale'), ['locale'], unique=True)

    # Seed the three default languages so the switcher works immediately.
    op.bulk_insert(
        sa.table(
            'site_languages',
            sa.column('locale', sa.String),
            sa.column('flag_class', sa.String),
            sa.column('label', sa.String),
            sa.column('is_active', sa.Boolean),
            sa.column('sort_order', sa.Integer),
        ),
        [
            {'locale': 'es_CL', 'flag_class': 'flag-country-cl', 'label': 'Español',   'is_active': True, 'sort_order': 0},
            {'locale': 'en_US', 'flag_class': 'flag-country-us', 'label': 'English',   'is_active': True, 'sort_order': 1},
            {'locale': 'pt_BR', 'flag_class': 'flag-country-br', 'label': 'Português', 'is_active': True, 'sort_order': 2},
        ],
    )


def downgrade():
    with op.batch_alter_table('site_languages', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_site_languages_locale'))
    op.drop_table('site_languages')

    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_site_settings_key'))
    op.drop_table('site_settings')
