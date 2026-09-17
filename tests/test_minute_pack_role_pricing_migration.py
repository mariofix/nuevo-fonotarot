import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_minute_pack_role_prices_migration_creates_table_and_seeds_roles(tmp_path):
    db_path = tmp_path / "migration.db"
    engine = sa.create_engine(f"sqlite:///{db_path}")
    metadata = sa.MetaData()

    sa.Table(
        "roles",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("permissions", sa.JSON(), nullable=True),
    )
    sa.Table(
        "minute_packs",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("minutes", sa.Integer, nullable=False),
        sa.Column("price", sa.Numeric(19, 4), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
    )
    metadata.create_all(engine)

    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "d9f8e7c6b5a4_add_minute_pack_role_prices.py"
    )
    spec = importlib.util.spec_from_file_location("minute_pack_role_prices_migration", migration_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()

        inspector = sa.inspect(connection)
        assert "minute_pack_role_prices" in inspector.get_table_names()

        role_names = {
            row[0]
            for row in connection.execute(
                sa.select(sa.column("name")).select_from(sa.table("roles")),
            )
        }
        assert {"leales-oro", "leales-plata", "leales-bronze"} <= role_names
