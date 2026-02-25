"""SQLAlchemy models for nuevo-fonotarot."""

from datetime import datetime, timezone

from flask_security import RoleMixin, UserMixin
from slugify import slugify

from app.extensions import db

# Many-to-many association table between users and roles.
roles_users = db.Table(
    "roles_users",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id")),
    db.Column("role_id", db.Integer, db.ForeignKey("roles.id")),
)


class Role(db.Model, RoleMixin):
    """Application role (e.g. 'admin')."""

    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.String(255))

    def __repr__(self) -> str:
        return f"<Role {self.name}>"


class User(db.Model, UserMixin):
    """Application user managed by Flask-Security."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=True, index=True)
    password = db.Column(db.String(256), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    # Required by Flask-Security ≥ 4.0 for token invalidation.
    fs_uniquifier = db.Column(db.String(64), unique=True, nullable=False)
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    roles = db.relationship(
        "Role", secondary=roles_users, backref=db.backref("users", lazy="dynamic")
    )

    def __repr__(self) -> str:
        return f"<User {self.email}>"


class StaticPage(db.Model):
    """A static HTML page served from a configurable URL path.

    The ``content`` field stores raw HTML and is served directly to the
    browser.  Access to create or edit pages must be restricted to trusted
    administrators only.
    """

    __tablename__ = "static_pages"

    id = db.Column(db.Integer, primary_key=True)
    path = db.Column(db.String(255), unique=True, nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    content = db.Column(db.Text, nullable=False, default="")
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<StaticPage {self.path}>"

    @staticmethod
    def normalize_path(raw_path: str) -> str:
        """Return a normalised path string from *raw_path*.

        Each path segment is slugified so that the stored value is always
        URL-safe (e.g. ``about-us``, ``level1/level2``).  Leading and
        trailing slashes are stripped.
        """
        segments = [s for s in raw_path.strip("/").split("/") if s]
        return "/".join(slugify(seg) for seg in segments)
