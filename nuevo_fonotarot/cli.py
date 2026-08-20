"""Flask CLI commands for managing i18n translations."""

import json
import os
import subprocess
import sys

import click
from flask import current_app
from flask.cli import with_appcontext


# Path helpers — all relative to the project root (where babel.cfg lives).
def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _translations_dir() -> str:
    return os.path.join(_project_root(), "nuevo_fonotarot", "translations")


def _pot_file() -> str:
    return os.path.join(_translations_dir(), "messages.pot")


def _po_file(locale: str) -> str:
    return os.path.join(_translations_dir(), locale, "LC_MESSAGES", "messages.po")


def _babel_cfg() -> str:
    return os.path.join(_project_root(), "babel.cfg")


def _run(*args: str) -> None:
    """Run a pybabel sub-command, streaming output to the terminal."""
    cmd = [sys.executable, "-m", "babel.messages.frontend"] + list(args)
    result = subprocess.run(cmd, cwd=_project_root())
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def _extract_pot() -> None:
    """Re-extract all marked strings into messages.pot."""
    os.makedirs(_translations_dir(), exist_ok=True)
    _run(
        "extract",
        "-F",
        _babel_cfg(),
        "-k",
        "_l",
        "-k",
        "lazy_gettext",
        "-o",
        _pot_file(),
        ".",
    )


def _compile(locale: str) -> None:
    """Compile a single locale's .po → .mo."""
    _run(
        "compile",
        "-d",
        _translations_dir(),
        "-l",
        locale,
    )


def _load_available_langs() -> list[list[str]]:
    """Return the AVAILABLE_LANGUAGES list from app config."""
    return current_app.config.get("AVAILABLE_LANGUAGES", [])


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


@click.group("lang")
def lang_cli() -> None:
    """Manage i18n translation catalogues and available languages."""


@lang_cli.command("new")
@click.argument("locale")
@click.argument("label")
@click.option(
    "--short",
    default=None,
    help="Short code for the language switcher (defaults to the language part of the locale, e.g. 'fr' for 'fr_FR').",
)
@with_appcontext
def lang_new(locale: str, label: str, short: str | None) -> None:
    """Create a NEW language catalogue.

    LOCALE  Babel locale code, e.g. fr_FR\n
    LABEL   Human-readable name shown as tooltip, e.g. Français

    The command refuses to proceed if LOCALE is already in AVAILABLE_LANGUAGES.
    After running, add the new entry to AVAILABLE_LANGUAGES in config.py.
    """
    if short is None:
        short = locale.split("_")[0].lower()

    langs = _load_available_langs()
    existing_locales = [entry[1] for entry in langs]

    if locale in existing_locales:
        click.echo(
            click.style(
                f"✗ Locale '{locale}' is already in AVAILABLE_LANGUAGES (config.py).",
                fg="red",
            )
        )
        raise SystemExit(1)

    po = _po_file(locale)
    if os.path.exists(po):
        click.echo(
            click.style(
                f"✗ PO file already exists at {po}. Remove it manually or use 'flask lang update' to refresh it.",
                fg="red",
            )
        )
        raise SystemExit(1)

    click.echo(f"→ Extracting strings into {_pot_file()} …")
    _extract_pot()

    click.echo(f"→ Initialising catalogue for {locale} …")
    _run("init", "-i", _pot_file(), "-d", _translations_dir(), "-l", locale)

    click.echo(f"→ Compiling {locale} …")
    _compile(locale)

    click.echo(
        click.style(
            f"✓ Language '{locale}' ({label}) catalogue created.\n"
            f"  Next steps:\n"
            f'    1. Add ["{short}", "{locale}", "{label}"] to AVAILABLE_LANGUAGES in config.py\n'
            f"    2. Translate {po}\n"
            f"    3. Run 'flask lang update {locale}'",
            fg="green",
        )
    )


@lang_cli.command("update")
@click.argument("locale", required=False, default=None)
@with_appcontext
def lang_update(locale: str | None) -> None:
    """Update PO catalogue(s) from source strings and recompile.

    LOCALE  Optional Babel locale code. When omitted all registered locales
            are updated.
    """
    langs = _load_available_langs()
    registered = [entry[1] for entry in langs]

    if locale:
        if locale not in registered:
            click.echo(
                click.style(
                    f"✗ Locale '{locale}' is not in AVAILABLE_LANGUAGES (config.py). "
                    "Use 'flask lang new' to create the catalogue, then add it to config.",
                    fg="red",
                )
            )
            raise SystemExit(1)
        targets = [locale]
    else:
        targets = registered

    click.echo(f"→ Extracting strings into {_pot_file()} …")
    _extract_pot()

    for loc in targets:
        po = _po_file(loc)
        if not os.path.exists(po):
            click.echo(
                click.style(
                    f"  ⚠ PO file not found for '{loc}' ({po}). Run 'flask lang new' to initialise it.",
                    fg="yellow",
                )
            )
            continue

        click.echo(f"→ Merging new strings into {loc} …")
        _run("update", "-i", _pot_file(), "-d", _translations_dir(), "-l", loc)

        click.echo(f"→ Compiling {loc} …")
        _compile(loc)

        click.echo(click.style(f"  ✓ {loc} updated.", fg="green"))

    if len(targets) > 1:
        click.echo(click.style("✓ All locales updated.", fg="green"))


# ---------------------------------------------------------------------------
# Promo stock seed command
# ---------------------------------------------------------------------------


@click.command("seed-promo")
@click.option("--stock", default=36, show_default=True, help="Number of free-trial promotions to make available.")
@with_appcontext
def seed_promo_cli(stock: int = 36) -> None:
    """Create or reset the free-trial promotion stock counter.

    Sets SiteSettings key ``promo_free_minutes_remaining`` to STOCK (default 36).
    If the key already exists it is overwritten with the new value.

    Example:\n
        flask seed-promo              # → 36\n
        flask seed-promo --stock 100  # → 100
    """
    from .extensions import db
    from .models import SiteSettings

    row = SiteSettings.query.filter_by(key="promo_free_minutes_remaining").first()
    if row is None:
        row = SiteSettings(
            key="promo_free_minutes_remaining",
            value=str(stock),
            module="promo",
            description="Número de canjes de 5 minutos gratuitos disponibles para nuevos usuarios",
        )
        db.session.add(row)
        action = "created"
    else:
        row.value = str(stock)
        action = "updated"

    db.session.commit()
    click.echo(
        click.style(
            f"✓ promo_free_minutes_remaining {action} → {stock}",
            fg="green",
        )
    )


# ---------------------------------------------------------------------------
# User management commands
# ---------------------------------------------------------------------------


@click.group("user")
def user_cli() -> None:
    """Manage users and user data."""


@user_cli.command("sync-firenze")
@click.option(
    "--filter",
    "filter_by",
    type=click.Choice(["all", "missing"]),
    default="missing",
    show_default=True,
    help="'all': process every user; 'missing': process only users without a firenze_client_id.",
)
@with_appcontext
def user_sync_firenze(filter_by: str) -> None:
    """Run post-registration steps for existing users.

    Processes each user through the standard post-registration flow (e.g., Firenze sync).
    Use this to backfill Firenze client_ids for existing users who registered
    before this feature was available.

    --filter all     Process every user (slow for large user bases)
    --filter missing Process only users without a firenze_client_id (default, faster)
    """
    from .actions import process_user_registration
    from .models import User

    if filter_by == "missing":
        query = User.query.filter(User.firenze_client_id.is_(None))
    else:
        query = User.query

    users = query.all()
    if not users:
        click.echo(click.style("✓ No users to process.", fg="green"))
        return

    click.echo(f"→ Processing {len(users)} user(s) …")
    processed = 0
    errors = 0

    with click.progressbar(
        users,
        label="Progress",
        show_pos=True,
    ) as bar:
        for user in bar:
            try:
                if process_user_registration(user):
                    processed += 1
            except Exception:
                errors += 1

    click.echo()
    click.echo(
        click.style(
            f"✓ Done: {processed} user(s) processed, {errors} error(s).",
            fg="green",
        )
    )


@user_cli.command("sync-email-signin")
@click.option(
    "--filter",
    "filter_by",
    type=click.Choice(["all", "missing"]),
    default="missing",
    show_default=True,
    help="'all': process every user; 'missing': process only users without an email signin secret.",
)
@with_appcontext
def user_sync_email_signin(filter_by: str) -> None:
    """Backfill unified-signin email secrets for existing users."""
    from .auth_handlers import ensure_user_email_signin
    from .models import User

    def _has_email_signin(user: User) -> bool:
        if isinstance(user.us_totp_secrets, str):
            if not user.us_totp_secrets:
                return False
            try:
                secrets = json.loads(user.us_totp_secrets)
            except json.JSONDecodeError:
                return False
        else:
            secrets = user.us_totp_secrets or {}
        return "email" in secrets

    users = User.query.all()
    if filter_by == "missing":
        users = [user for user in users if not _has_email_signin(user)]

    if not users:
        click.echo(click.style("✓ No users to process.", fg="green"))
        return

    click.echo(f"→ Processing {len(users)} user(s) …")
    updated = 0

    with click.progressbar(
        users,
        label="Progress",
        show_pos=True,
    ) as bar:
        for user in bar:
            if ensure_user_email_signin(user):
                updated += 1

    click.echo()
    click.echo(
        click.style(
            f"✓ Done: {updated} user(s) updated.",
            fg="green",
        )
    )


@click.group("legacy")
def legacy_cli() -> None:
    """Import Data from old systems."""


def row_to_dict(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


@legacy_cli.command("ventas-portal")
@click.option("--dry-run", is_flag=True, help="Count what would be imported without writing anything.")
@click.option("--offset", default=0, show_default=True, help="SQL OFFSET into the legacy table.")
@click.option("--limit", type=int, default=None, help="SQL LIMIT — max rows fetched for this batch.")
@click.option(
    "--from-date",
    "from_date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    required=True,
    help="Start date (inclusive), format YYYY-MM-DD.",
)
@click.option(
    "--to-date",
    "to_date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    required=True,
    help="End date (inclusive), format YYYY-MM-DD.",
)
@with_appcontext
def import_legacy_sales_cmd(dry_run, offset, limit, from_date, to_date):
    from datetime import datetime, time

    from sqlalchemy import text

    from .extensions import db
    from .utils import import_legacy_sales

    if from_date > to_date:
        raise click.UsageError(f"--from-date ({from_date.date()}) is after --to-date ({to_date.date()}).")

    range_start = from_date  # 00:00:00
    range_end = datetime.combine(to_date.date(), time(23, 59, 59))

    query = text("""
        SELECT c.*, cl.client_id, p.valor
        FROM zvn_portal.zvn_compra c
        JOIN zvn_portal.zvn_cliente cl ON c.cliente_id = cl.id
        JOIN zvn_portal.zvn_producto p ON p.id = c.producto_id
        WHERE c.estado IN ('Pagado')
          AND cl.servicio_id = 1
          AND c.creado BETWEEN :range_start AND :range_end
        ORDER BY c.id ASC
        LIMIT :limit OFFSET :offset
        """)
    result = db.session.execute(
        query,
        {
            "range_start": range_start,
            "range_end": range_end,
            "offset": offset,
            "limit": limit or 9999999999,
        },
    )
    rows = result.mappings().all()

    stats = import_legacy_sales(rows, dry_run=dry_run)
    click.echo(f"{'[DRY RUN] ' if dry_run else ''}date_range={range_start.date()}..{range_end.date()} {stats}")
