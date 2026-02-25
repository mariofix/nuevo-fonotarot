"""add site_settings table with available_lang seed

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

# Default available languages stored as a JSON value.
# Format per entry: [short_code, locale, label]
_AVAILABLE_LANG_VALUE = (
    '[["es","es_CL","Español"],'
    '["en","en_US","English"],'
    '["pt","pt_BR","Português"]]'
)


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

    # Seed the available languages setting.
    op.bulk_insert(
        sa.table(
            'site_settings',
            sa.column('key', sa.String),
            sa.column('value', sa.Text),
            sa.column('description', sa.String),
            sa.column('module', sa.String),
        ),
        [
            {
                'key': 'available_lang',
                'value': _AVAILABLE_LANG_VALUE,
                'description': (
                    'Available languages for the public language switcher. '
                    'JSON array of [short_code, locale, label] entries, '
                    'e.g. [["es","es_CL","Español"],["en","en_US","English"]]'
                ),
                'module': 'general',
            },
        ],
    )


def downgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_site_settings_key'))
    op.drop_table('site_settings')
