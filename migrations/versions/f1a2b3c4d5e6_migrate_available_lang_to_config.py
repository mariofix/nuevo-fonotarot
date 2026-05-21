"""Move available_lang out of site_settings; seed default_currency and default_language

Revision ID: f1a2b3c4d5e6
Revises: d1e2f3a4b5c6
Create Date: 2026-03-16 00:00:00.000000

Changes
-------
- Removes the ``available_lang`` row from site_settings (now lives in
  ``AVAILABLE_LANGUAGES`` in config.py).
- Seeds ``default_currency`` (``CLP``) and ``default_language`` (``es_CL``)
  so admins can override the deploy-time defaults from the admin panel.
"""

import sqlalchemy as sa
from alembic import op

revision = "f1a2b3c4d5e6"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None

_settings_table = sa.table(
    "site_settings",
    sa.column("key", sa.String),
    sa.column("value", sa.Text),
    sa.column("description", sa.String),
    sa.column("module", sa.String),
)


def upgrade():
    # Remove available_lang — now managed statically in config.py.
    op.execute(sa.delete(_settings_table).where(_settings_table.c.key == "available_lang"))

    # Seed runtime-overridable business defaults.
    op.bulk_insert(
        _settings_table,
        [
            {
                "key": "default_currency",
                "value": "CLP",
                "description": (
                    "ISO 4217 currency code used for new orders when no "
                    "other currency is specified.  Overrides the "
                    "DEFAULT_CURRENCY environment variable at runtime."
                ),
                "module": "general",
            },
            {
                "key": "default_language",
                "value": "es_CL",
                "description": (
                    "Fallback locale used when a visitor has no session "
                    "language and Accept-Language negotiation yields no "
                    "match.  Overrides the BABEL_DEFAULT_LOCALE environment "
                    "variable at runtime."
                ),
                "module": "general",
            },
        ],
    )


def downgrade():
    # Remove the seeded keys.
    op.execute(sa.delete(_settings_table).where(_settings_table.c.key.in_(["default_currency", "default_language"])))

    # Restore the available_lang row with the original default value.
    op.bulk_insert(
        _settings_table,
        [
            {
                "key": "available_lang",
                "value": ('[["es","es_CL","Español"],["en","en_US","English"],["pt","pt_BR","Português"]]'),
                "description": (
                    "Available languages for the public language switcher. "
                    "JSON array of [short_code, locale, label] entries, "
                    'e.g. [["es","es_CL","Español"],["en","en_US","English"]]'
                ),
                "module": "general",
            },
        ],
    )
