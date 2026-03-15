# Copilot Instructions for nuevo-fonotarot

## Project Overview

**nuevo-fonotarot** is a Flask web application for Fonotarot — a Chilean tarot-by-phone service. The app handles the public marketing site, a blog, an e-commerce store (digital products sold via Chilean payment gateways), user accounts, and an internal admin panel for operators.

The primary language of the UI and content is **Spanish (es_CL)**. All user-facing strings in templates and Python code must be wrapped with Flask-Babel's `_()` or `_l()` for translation.

---

## Technology Stack

| Layer | Library / Tool |
|---|---|
| Web framework | Flask 3.0+ |
| ORM / DB | Flask-SQLAlchemy + SQLAlchemy 2 (mapped_column style) |
| Migrations | Flask-Migrate (Alembic) |
| Authentication | Flask-Security (roles: `admin`) |
| Admin panel | Flask-Admin + `flask_admin_tabler` (Tabler UI theme) |
| i18n | Flask-Babel (default locale `es_CL`) |
| Rate limiting | Flask-Limiter |
| Email | Flask-Mail |
| Payments | `flask-merchants` with Khipu and Flow providers |
| Templates | Jinja2 (all HTML lives in `nuevo_fonotarot/templates/`) |
| Python | 3.13+ — use modern type hints (`str | None`, `list[X]`) |
| Build | Hatchling (`pyproject.toml`) |
| Logging | Django-style `LOGGING` dict in `config.py`, applied via `logging.config.dictConfig` |

---

## Repository Layout

```
nuevo_fonotarot/       # Main application package
  flask_app.py         # Application factory: create_flask()
  extensions.py        # Extension singletons (db, admin, security, …)
  models.py            # SQLAlchemy models
  admin.py             # Flask-Admin views & SecureAdminIndexView
  config.py            # Config classes (DevelopmentConfig, ProductionConfig, TestingConfig)
  log.py               # get_logger() helper
  account/             # Blueprint: user registration/login helpers
  content/             # Blueprint: static pages (content_bp) + blog (blog_bp)
  tienda/              # Blueprint: e-commerce store
  lab/                 # Blueprint: experimental/internal routes
  legacy/              # Blueprint: legacy telephony data
  templates/           # Jinja2 templates (base.html, index.html, …)
  static/              # Project static files
  translations/        # Babel .po/.mo files

flask_admin_tabler/    # Local fork of the Tabler theme for Flask-Admin
flask-admin-source/    # Vendored Flask-Admin source (do not modify)
migrations/            # Alembic migration scripts
config.py              # Top-level config loader (imports from nuevo_fonotarot indirectly)
app.py / wsgi.py / asgi.py  # Entry points
file.env               # Example environment file — copy to .env
```

---

## Architecture Conventions

### Application Factory
Always use `create_flask(config_name)` from `nuevo_fonotarot/flask_app.py`. Do not instantiate `Flask` anywhere else.

### Extensions
All Flask extension objects live in `nuevo_fonotarot/extensions.py` as module-level singletons. They are initialised (`.init_app(app)`) inside `_init_extensions()` in `flask_app.py`. **Do not call `.init_app()` outside the factory.**

### Blueprint registration order matters
`TablerTheme.init_app(app)` **must** be called before `admin.init_app(app)` so the Tabler templates take priority. See `flask_app.py` for the correct order.

### Models
- Use SQLAlchemy 2 `Mapped` / `mapped_column` style (not legacy `Column`).
- All models live in `nuevo_fonotarot/models.py` unless they belong to a `flask-merchants` sub-package.
- Timestamps use `datetime.now(timezone.utc)`.

### Admin panel
- Secure every admin view by inheriting from `SecureModelView` (defined in `admin.py`).
- Icons use Tabler Icons (`ti ti-*`) — not Font Awesome or Glyphicons.
- Pass `menu_icon_type` / `menu_icon_value` as **constructor arguments** to `admin.add_view()`, not as class attributes.

### Logging
Use `get_logger(__name__)` from `nuevo_fonotarot.log` for all module-scoped loggers. Never use `print()` for diagnostics. Control verbosity with the `LOG_LEVEL` environment variable.

### Configuration
All runtime settings come from environment variables loaded by `python-dotenv` from `.env`. Copy `file.env` → `.env` and fill in values. Do **not** hardcode secrets. Use `os.environ.get("KEY", "default")`.

---

## Development Workflow

### Setup
```bash
cp file.env .env          # Fill in SECRET_KEY and SECURITY_PASSWORD_SALT at minimum
pip install -e .
flask db upgrade          # Apply migrations
flask run                 # Start dev server on http://127.0.0.1:5000
```

### Database migrations
```bash
flask db migrate -m "describe the change"
flask db upgrade
```

### Translations (Babel)
```bash
pybabel extract -F babel.cfg -k _l -o messages.pot .
pybabel update -i messages.pot -d nuevo_fonotarot/translations
# Edit .po files, then compile:
pybabel compile -d nuevo_fonotarot/translations
```

### CLI commands
```bash
flask seed-pages    # Seed default static pages
flask seed-promo    # Seed demo promotions
flask lang          # Language utilities
```

---

## Code Conventions

Follow all standards in `CLAUDE.md` (at repository root). Key points:

- **Conventional commits**: `feat:`, `fix:`, `refactor:`, `chore:`, `docs:`, `test:`
- **No inline HTML** in Python — always use Jinja2 templates.
- **No hardcoded credentials** — use environment variables.
- **No dead code** — remove unused imports and commented-out blocks.
- **Type hints** on all public functions and methods.
- **Docstrings** on all public APIs.
- **Parameterised queries only** — never concatenate SQL strings.
- **CSRF protection** is global via `flask_wtf.csrf.CSRFProtect` — do not exempt routes without a documented reason.

---

## Testing

There is currently no dedicated application test suite. When writing tests:

- Use `TestingConfig` (`SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"`, `WTF_CSRF_ENABLED = False`).
- Create the app with `create_flask("testing")`.
- Place tests in a top-level `tests/` directory following `pytest` conventions.

---

## Payment Integrations

- **Flow** (`FLOW_API_KEY`, `FLOW_SECRET_KEY`, `FLOW_API_URL`): use sandbox URL for development.
- **Khipu** (`KHIPU_API_KEY`): Chilean bank-transfer gateway.
- Both are wired via `flask-merchants` in `_init_merchants()`. Do not initialise payment providers directly.

---

## Security Notes

- Authentication is handled by Flask-Security. Admin routes require the `admin` role.
- Rate limiting is applied globally (200/day, 50/hour per IP) and additionally at 120/hour + 20/minute for the `/admin` blueprint.
- All forms use CSRF tokens automatically via Flask-WTF.
- Secrets (`SECRET_KEY`, `SECURITY_PASSWORD_SALT`) **must** be changed from their development defaults before deploying to production.
