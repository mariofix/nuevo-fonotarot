# Internationalization (i18n) Guide

This project uses [Flask-Babel](https://python-babel.github.io/flask-babel/) for
translations. Source strings live in
`nuevo_fonotarot/translations/<locale>/LC_MESSAGES/messages.po`; compiled
binaries (`messages.mo`) are git-ignored and must be compiled before running.

---

## Available languages

Languages shown in the public switcher are defined in `config.py`:

```python
AVAILABLE_LANGUAGES: list = [
    ["es", "es_CL", "Chile"],
    ["es", "es_MX", "México"],
]
```

Each entry: `[short_code, locale, label]`

| Field        | Description                                          | Example   |
|--------------|------------------------------------------------------|-----------|
| `short_code` | Short language identifier (not used for routing)     | `"es"`    |
| `locale`     | Babel locale code — must match a `translations/` dir | `"es_CL"` |
| `label`      | Display name shown as the flag tooltip               | `"Chile"` |

The Tabler flag CSS class is **derived automatically** from the locale territory:
`es_CL` → `flag-country-cl`, `en_US` → `flag-country-us`, `pt_BR` → `flag-country-br`.

The default/fallback locale is set by `BABEL_DEFAULT_LOCALE` in `config.py`
(currently `"es_CL"`).

Inactive locales with translation files already present: `en_US`, `pt_BR` —
uncomment the corresponding entries in `AVAILABLE_LANGUAGES` to enable them.

---

## CLI commands

A `flask lang` command group is the recommended way to manage catalogues.

```
flask lang --help

Commands:
  new     Create a new language catalogue and compile it.
  update  Re-extract strings, merge into existing catalogue(s), and recompile.
```

### `flask lang new LOCALE LABEL [--short CODE]`

Creates the `.po` catalogue and compiles it to `.mo`. The command **refuses to
proceed** if the locale is already registered or the `.po` file already exists.

```bash
# Add French (France)
flask lang new fr_FR Français

# Add German with an explicit short code
flask lang new de_DE Deutsch --short de
```

After running, open the generated
`nuevo_fonotarot/translations/<locale>/LC_MESSAGES/messages.po`, fill in the
`msgstr` values, then recompile with `flask lang update <locale>`.

Finally, add the new entry to `AVAILABLE_LANGUAGES` in `config.py` to make it
appear in the public switcher (see [Adding a new language](#adding-a-new-language)).

### `flask lang update [LOCALE]`

Re-extracts all marked strings, merges new/changed strings into the existing
`.po` file(s), and recompiles. When `LOCALE` is omitted, **all** registered
locales are updated.

```bash
# Update a single locale
flask lang update fr_FR

# Update every locale
flask lang update
```

---

## Adding a new language

See [`new-country.md`](new-country.md) for the complete step-by-step guide,
including flag SVG verification, `config.py` registration, and the PR workflow.

**Quick summary:**

```bash
# 1. Scaffold the catalogue
flask lang new fr_FR Français

# 2. Translate: edit nuevo_fonotarot/translations/fr_FR/LC_MESSAGES/messages.po

# 3. Recompile after translating
flask lang update fr_FR

# 4. Register in config.py → AVAILABLE_LANGUAGES
# 5. Verify flag SVG: nuevo_fonotarot/static/vendor/tabler/img/flags/fr.svg
```

---

## Updating existing translation strings

Run these commands from the project root whenever you add or change `_("…")`
calls in Python files or Jinja2 templates:

```bash
# 1. Re-extract all marked strings into the POT template
uv run pybabel extract -F babel.cfg \
    -k _l -k lazy_gettext \
    -o nuevo_fonotarot/translations/messages.pot .

# 2. Merge new/changed strings into every existing PO catalogue
uv run pybabel update \
    -i nuevo_fonotarot/translations/messages.pot \
    -d nuevo_fonotarot/translations

# 3. Edit the PO files to fill in the new msgstr values
#    Files: nuevo_fonotarot/translations/<locale>/LC_MESSAGES/messages.po

# 4. Compile the updated catalogues
uv run pybabel compile -d nuevo_fonotarot/translations
```

Or use the CLI shortcut:

```bash
flask lang update          # all locales
flask lang update es_CL    # one locale
```

After compiling, restart the Flask development server so the new `.mo` files
are loaded.

---

## Marking strings for translation

**Python:**

```python
from flask_babel import gettext as _, lazy_gettext as _l

flash(_("Operación exitosa"))           # eager — inside a request context
label = _l("Nombre de usuario")         # lazy — safe outside request context
```

**Jinja2 templates** (`_()` is injected automatically):

```jinja2
{{ _("Tarotistas") }}
```

After adding new strings, run `flask lang update` to extract and merge them
into all existing catalogues.
