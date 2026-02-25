# Internationalization (i18n) Guide

This project uses [Flask-Babel](https://python-babel.github.io/flask-babel/) for
translations. Source strings live in
`nuevo_fonotarot/translations/<locale>/LC_MESSAGES/messages.po`; compiled
binaries are in `messages.mo` (git-ignored).

## Available languages

Languages shown in the public switcher are stored in the database under
`SiteSettings.key = "available_lang"` (Admin → **Sitio → Configuración**).

The value is a JSON array of three-item lists:

```json
[
  ["es", "es_CL", "Español"],
  ["en", "en_US", "English"],
  ["pt", "pt_BR", "Português"]
]
```

Each entry: `[short_code, locale, label]`

| Field        | Description                                        | Example      |
|--------------|----------------------------------------------------|--------------|
| `short_code` | Short identifier (not used for routing)            | `"es"`       |
| `locale`     | Babel locale code — must match a `translations/` dir | `"es_CL"` |
| `label`      | Display name shown as the flag tooltip             | `"Español"`  |

The Tabler flag CSS class is **derived automatically** from the locale territory:
`es_CL` → `flag-country-cl`, `en_US` → `flag-country-us`, `pt_BR` → `flag-country-br`.

The default/fallback locale is set by `DEFAULT_LANGUAGE` in `config.py`
(or the `DEFAULT_LANGUAGE` environment variable).

---

## CLI commands

A `flask lang` command group is the recommended way to manage catalogues.

```
flask lang --help

Commands:
  new     Create a new language catalogue and register it.
  update  Update PO catalogue(s) from source strings and recompile.
```

### `flask lang new LOCALE LABEL [--short CODE]`

Creates the `.po` catalogue, compiles it to `.mo`, and appends the new
language to `SiteSettings.available_lang` in one step.  The command
**refuses to proceed** if the locale is already registered or the `.po` file
already exists.

```bash
# Add French (France)
flask lang new fr_FR Français

# Add German with an explicit short code
flask lang new de_DE Deutsch --short de
```

After running, open the generated
`nuevo_fonotarot/translations/<locale>/LC_MESSAGES/messages.po` and fill in
the `msgstr` values, then run `flask lang update <locale>` to recompile.

### `flask lang update [LOCALE]`

Re-extracts all marked strings, merges new/changed strings into the existing
`.po` file(s), and recompiles.  When `LOCALE` is omitted, **all** registered
locales are updated.

```bash
# Update a single locale
flask lang update fr_FR

# Update every registered locale
flask lang update
```

---

## Updating existing translation strings manually

If you prefer to run the individual `pybabel` steps yourself:

```bash
# 1. Re-extract all marked strings into the POT template
pybabel extract -F babel.cfg -o nuevo_fonotarot/translations/messages.pot .

# 2. Merge new/changed strings into every existing PO catalogue
pybabel update \
    -i nuevo_fonotarot/translations/messages.pot \
    -d nuevo_fonotarot/translations

# 3. Edit the PO files to fill in the new msgstr values
#    Files: nuevo_fonotarot/translations/<locale>/LC_MESSAGES/messages.po

# 4. Compile the updated catalogues
pybabel compile -d nuevo_fonotarot/translations
```

---

## Adding a new language manually

### 1. Create the translation catalogue

```bash
# Replace <locale> with the Babel locale code, e.g. "fr_FR"
pybabel init \
    -i nuevo_fonotarot/translations/messages.pot \
    -d nuevo_fonotarot/translations \
    -l <locale>
```

Open the generated
`nuevo_fonotarot/translations/<locale>/LC_MESSAGES/messages.po`
and translate every `msgstr ""` entry.

### 2. Compile

```bash
pybabel compile -d nuevo_fonotarot/translations
```

### 3. Register in the database

Log in to the admin panel (Admin → **Sitio → Configuración**) and edit the
`available_lang` row. Add your new entry to the JSON array:

```json
[
  ["es", "es_CL", "Español"],
  ["en", "en_US", "English"],
  ["pt", "pt_BR", "Português"],
  ["fr", "fr_FR", "Français"]
]
```

The Tabler flag for `fr_FR` is automatically resolved to `flag-country-fr`.
Check the full flag list at `dashboard/flags.html` to confirm the flag exists.

### 4. (Optional) Set as default

To make the new language the primary fallback, update `config.py`:

```python
DEFAULT_LANGUAGE: str = os.environ.get("DEFAULT_LANGUAGE", "fr_FR")
```

Or set the `DEFAULT_LANGUAGE` environment variable in your `.env` file:

```dotenv
DEFAULT_LANGUAGE=fr_FR
```

---

## Marking strings for translation

**Python:**
```python
from flask_babel import gettext as _, lazy_gettext as _l

flash(_("Operación exitosa"))
```

**Jinja2 templates:**
```jinja
{{ _("Tarotistas") }}
```

After adding new strings, run `flask lang update` or the manual steps above.


The Tabler flag CSS class is **derived automatically** from the locale territory:
`es_CL` → `flag-country-cl`, `en_US` → `flag-country-us`, `pt_BR` → `flag-country-br`.

The default/fallback locale is set by `DEFAULT_LANGUAGE` in `config.py`
(or the `DEFAULT_LANGUAGE` environment variable).

---

## Updating existing translation strings

Run these commands from the project root whenever you add or change `_("…")`
calls in Python files or Jinja2 templates:

```bash
# 1. Re-extract all marked strings into the POT template
uv run pybabel extract -F babel.cfg -o nuevo_fonotarot/translations/messages.pot .

# 2. Merge new/changed strings into every existing PO catalogue
uv run pybabel update \
    -i nuevo_fonotarot/translations/messages.pot \
    -d nuevo_fonotarot/translations

# 3. Edit the PO files to fill in the new msgstr values
#    (use a text editor or a PO editor such as Poedit)
#    Files: nuevo_fonotarot/translations/<locale>/LC_MESSAGES/messages.po

# 4. Compile the updated catalogues
uv run pybabel compile -d nuevo_fonotarot/translations
```

After compiling, restart the Flask development server so the new `.mo` files
are loaded.

---

## Adding a new language

### 1. Create the translation catalogue

```bash
# Replace <locale> with the Babel locale code, e.g. "fr_FR"
uv run pybabel init \
    -i nuevo_fonotarot/translations/messages.pot \
    -d nuevo_fonotarot/translations \
    -l <locale>
```

Open the generated
`nuevo_fonotarot/translations/<locale>/LC_MESSAGES/messages.po`
and translate every `msgstr ""` entry.

### 2. Compile

```bash
uv run pybabel compile -d nuevo_fonotarot/translations
```

### 3. Register in the database

Log in to the admin panel (Admin → **Sitio → Configuración**) and edit the
`available_lang` row. Add your new entry to the JSON array:

```json
[
  ["es", "es_CL", "Español"],
  ["en", "en_US", "English"],
  ["pt", "pt_BR", "Português"],
  ["fr", "fr_FR", "Français"]
]
```

The Tabler flag for `fr_FR` is automatically resolved to `flag-country-fr`.
Check the full flag list at `dashboard/flags.html` to confirm the flag exists.

### 4. (Optional) Set as default

To make the new language the primary fallback, update `config.py`:

```python
DEFAULT_LANGUAGE: str = os.environ.get("DEFAULT_LANGUAGE", "fr_FR")
```

Or set the `DEFAULT_LANGUAGE` environment variable in your `.env` file:

```dotenv
DEFAULT_LANGUAGE=fr_FR
```

---

## Marking strings for translation

**Python:**
```python
from flask_babel import gettext as _, lazy_gettext as _l

flash(_("Operación exitosa"))
```

**Jinja2 templates:**
```jinja
{{ _("Tarotistas") }}
```

After adding new strings, repeat the **Updating** steps above.
