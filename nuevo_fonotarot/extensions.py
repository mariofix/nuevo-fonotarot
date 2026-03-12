"""Flask extensions instantiated here to avoid circular imports."""

from flask_admin import Admin
from flask_babel import Babel
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_mail import Mail
from flask_merchants import FlaskMerchants
from flask_migrate import Migrate
from flask_security.core import Security
from flask_security.datastore import SQLAlchemyUserDatastore
from flask_sqlalchemy import SQLAlchemy
from flask_debugtoolbar import DebugToolbarExtension
from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect()
mail = Mail()
db = SQLAlchemy()
migrate = Migrate()
limiter = Limiter(
    key_func=get_remote_address, default_limits=["200 per day", "50 per hour"]
)
babel = Babel()
security = Security()
admin = Admin(name="Fonotarot")
merchants_ext = FlaskMerchants()
toolbar = DebugToolbarExtension()
# Set by the application factory after Security is initialised.
user_datastore: SQLAlchemyUserDatastore | None = None
