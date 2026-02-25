"""Flask CLI commands for managing i18n translations."""

from __future__ import annotations

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
        "-F", _babel_cfg(),
        "-o", _pot_file(),
        ".",
    )


def _compile(locale: str) -> None:
    """Compile a single locale's .po → .mo."""
    _run(
        "compile",
        "-d", _translations_dir(),
        "-l", locale,
    )


def _load_available_langs() -> list[list[str]]:
    """Return the available_lang list from SiteSettings (or fallback)."""
    try:
        from .models import SiteSettings
        raw = SiteSettings.get("available_lang")
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return [
        ["es", "es_CL", "Español"],
        ["en", "en_US", "English"],
        ["pt", "pt_BR", "Português"],
    ]


def _save_available_langs(langs: list[list[str]]) -> None:
    """Persist the available_lang list back to SiteSettings."""
    from .extensions import db
    from .models import SiteSettings

    row = SiteSettings.query.filter_by(key="available_lang").first()
    if row:
        row.value = json.dumps(langs, ensure_ascii=False)
    else:
        row = SiteSettings(
            key="available_lang",
            value=json.dumps(langs, ensure_ascii=False),
            description=(
                "Available languages for the public language switcher. "
                "JSON array of [short_code, locale, label] entries."
            ),
            module="general",
        )
        db.session.add(row)
    db.session.commit()


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group("lang")
def lang_cli() -> None:
    """Manage i18n translation catalogues and available languages."""


@lang_cli.command("new")
@click.argument("locale")
@click.argument("label")
@click.option("--short", default=None,
              help="Short code stored in SiteSettings (defaults to the language part of the locale, e.g. 'fr' for 'fr_FR').")
@with_appcontext
def lang_new(locale: str, label: str, short: str | None) -> None:
    """Create a NEW language catalogue and register it in SiteSettings.

    LOCALE  Babel locale code, e.g. fr_FR\n
    LABEL   Human-readable name shown as tooltip, e.g. Français

    The command refuses to proceed if LOCALE is already registered.
    """
    if short is None:
        short = locale.split("_")[0].lower()

    langs = _load_available_langs()
    existing_locales = [entry[1] for entry in langs]

    if locale in existing_locales:
        click.echo(
            click.style(
                f"✗ Locale '{locale}' is already registered in SiteSettings (available_lang).",
                fg="red",
            )
        )
        raise SystemExit(1)

    po = _po_file(locale)
    if os.path.exists(po):
        click.echo(
            click.style(
                f"✗ PO file already exists at {po}. "
                "Remove it manually or use 'flask lang update' to refresh it.",
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

    langs.append([short, locale, label])
    _save_available_langs(langs)

    click.echo(
        click.style(
            f"✓ Language '{locale}' ({label}) created and registered.\n"
            f"  Next: translate {po}, then run 'flask lang update {locale}'.",
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
                    f"✗ Locale '{locale}' is not registered in SiteSettings. "
                    "Use 'flask lang new' to add it first.",
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
                    f"  ⚠ PO file not found for '{loc}' ({po}). "
                    "Run 'flask lang new' to initialise it.",
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
