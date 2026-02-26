"""Flask extensions instantiated here to avoid circular imports."""

from flask_admin import Admin
from flask_babel import Babel
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_merchants import FlaskMerchants
from flask_migrate import Migrate
from flask_security.core import Security
from flask_sqlalchemy import SQLAlchemy
from flask_admin_tabler import TablerTheme

db = SQLAlchemy()
migrate = Migrate()
limiter = Limiter(key_func=get_remote_address, default_limits=["200 per day", "50 per hour"])
babel = Babel()
security = Security()
# Apply Tabler theme before creating the Admin instance.
theme = TablerTheme()

admin = Admin(name="Fonotarot", theme=theme)
merchants_ext = FlaskMerchants()
