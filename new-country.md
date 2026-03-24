# Adding a New Country / Language

Step-by-step guide for adding a new language to the public switcher.
Example throughout: **Argentine Spanish** (`es_AR`).

---

## 1. Create the translation catalogue

Run from the project root. This extracts all marked strings, creates the `.po`
file, and compiles the initial `.mo`:

```bash
flask lang new es_AR Argentina
```

General form:

```bash
flask lang new <LOCALE> <LABEL> [--short CODE]
```

| Argument | Description | Example |
|---|---|---|
| `LOCALE` | Babel locale code — language + territory | `es_AR`, `en_US`, `pt_BR` |
| `LABEL` | Flag tooltip shown in the language switcher | `Argentina` |
| `--short` | Short language code (optional, defaults to first 2 chars) | `es` |

The command will refuse to proceed if the locale is already registered or its
`.po` file already exists.

---

## 2. Translate the strings

Open the generated file and fill in every empty `msgstr ""`:

```
nuevo_fonotarot/translations/es_AR/LC_MESSAGES/messages.po
```

Use a plain text editor or a dedicated PO editor such as
[Poedit](https://poedit.net/) or [Lokalize](https://apps.kde.org/lokalize/).

Each entry looks like:

```po
#: nuevo_fonotarot/templates/base.html:421
msgid "Tarotistas"
msgstr "Tarotistas"   ← fill this in
```

When done, recompile:

```bash
flask lang update es_AR
```

---

## 3. Register in `config.py`

Open `config.py` and add the new entry to `AVAILABLE_LANGUAGES`:

```python
AVAILABLE_LANGUAGES: list = [
    ["es", "es_CL", "Chile"],
    ["es", "es_MX", "México"],
    ["es", "es_AR", "Argentina"],   # ← add this line
]
```

Format: `[short_code, locale, label]` — the `locale` must match the directory
name created in step 1.

The Tabler flag CSS class is derived automatically:
`es_AR` → territory `ar` → `flag-country-ar`.

---

## 4. Verify the flag SVG exists

Check that the flag image is present:

```bash
ls nuevo_fonotarot/static/vendor/tabler/img/flags/ar.svg
```

If the file is missing, copy it from the Tabler npm package:

```bash
cp node_modules/@tabler/core/dist/img/flags/ar.svg \
   nuevo_fonotarot/static/vendor/tabler/img/flags/ar.svg
```

---

## 5. Test locally

Start the dev server and click the new flag in the language switcher.
Confirm:

- The flag renders correctly in the navbar.
- All UI strings appear in the new language (or fall back gracefully if
  `msgstr` entries are still empty).
- The `/account/set-language/es_AR` route stores the selection and redirects
  back.

---

## 6. Commit and open a PR

Stage only the source files — `.mo` binaries are git-ignored and compiled on
the server at deploy time.

```bash
git checkout -b claude/add-es-ar-language

git add \
  config.py \
  nuevo_fonotarot/translations/es_AR/LC_MESSAGES/messages.po \
  nuevo_fonotarot/static/vendor/tabler/img/flags/ar.svg   # only if newly added

git commit -m "feat(i18n): add Argentine Spanish (es_AR) locale"
```

Open a pull request targeting `main`. Once merged, run on the server:

```bash
flask lang update es_AR
```

(or restart the app — the deploy process should compile `.mo` files
automatically).

---

## Reference: currently active locales

| Locale | Label | Flag file |
|---|---|---|
| `es_CL` | Chile | `cl.svg` |
| `es_MX` | México | `mx.svg` |

Inactive locales with translation files already present:
`en_US`, `pt_BR` — uncomment in `AVAILABLE_LANGUAGES` to enable them.

---

## Reference: manual pybabel commands

The `flask lang` CLI wraps these calls. Use them directly if needed:

```bash
# Extract all marked strings → messages.pot
uv run pybabel extract -F babel.cfg \
    -k _l -k lazy_gettext \
    -o nuevo_fonotarot/translations/messages.pot .

# Initialise a new locale
uv run pybabel init \
    -i nuevo_fonotarot/translations/messages.pot \
    -d nuevo_fonotarot/translations \
    -l es_AR

# Merge new strings into an existing catalogue
uv run pybabel update \
    -i nuevo_fonotarot/translations/messages.pot \
    -d nuevo_fonotarot/translations \
    -l es_AR

# Compile .po → .mo
uv run pybabel compile -d nuevo_fonotarot/translations -l es_AR
```
