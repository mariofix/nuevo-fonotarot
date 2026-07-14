"""Flask extensions instantiated here to avoid circular imports."""

from daleks.contrib.flask_security_mail import DaleksMailUtil
from flask_admin import Admin
from flask_admin.theme import TablerTheme
from flask_babel import Babel
from flask_cors import CORS
from flask_debugtoolbar import DebugToolbarExtension
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_merchants import FlaskMerchants
from flask_migrate import Migrate
from flask_security.core import Security
from flask_security.datastore import SQLAlchemyUserDatastore
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

from .phone_util import PhoneUsernameUtil

cors = CORS()
csrf = CSRFProtect()
db = SQLAlchemy()
migrate = Migrate()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["240 per minute"],
    headers_enabled=True,
    swallow_errors=True,
    key_prefix="fonotarot",
)


@limiter.request_filter
def exempt_options():
    from flask import request

    return request.method == "OPTIONS"


babel = Babel()
security = Security(mail_util_cls=DaleksMailUtil, username_util_cls=PhoneUsernameUtil)
admin = Admin(name="Fonotarot", theme=TablerTheme(layout="fluid", theme_primary="lime", theme_radius="2"))
merchants_ext = FlaskMerchants()
toolbar = DebugToolbarExtension()
# Set by the application factory after Security is initialised.
user_datastore: SQLAlchemyUserDatastore | None = None
