"""SQLAlchemy models for nuevo-fonotarot."""

from datetime import datetime, timezone

from flask_security.core import RoleMixin, UserMixin
from slugify import slugify

from .extensions import db

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


class BlogPost(db.Model):
    """A blog post with a URL-friendly slug."""

    __tablename__ = "blog_posts"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(255), unique=True, nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    excerpt = db.Column(db.Text, nullable=True)
    content = db.Column(db.Text, nullable=False, default="")
    published = db.Column(db.Boolean, default=False, nullable=False)
    published_at = db.Column(db.DateTime, nullable=True)
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
        return f"<BlogPost {self.slug}>"

    @staticmethod
    def make_slug(title: str) -> str:
        """Return a URL-safe slug from *title*."""
        return slugify(title)


# ---------------------------------------------------------------------------
# Tienda models
# ---------------------------------------------------------------------------


class MinutePack(db.Model):
    """Prepaid tarot-minute package.

    Minutes never expire once purchased.
    """

    __tablename__ = "minute_packs"

    id = db.Column(db.Integer, primary_key=True)
    minutes = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Integer, nullable=False)  # price in CLP cents-free integer
    description = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_featured = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    def __repr__(self) -> str:
        return f"<MinutePack {self.minutes}min ${self.price}>"

    @property
    def price_display(self) -> str:
        """Format price with thousands separator (CLP style)."""
        return f"{self.price:,}".replace(",", ".")


class SubscriptionPlan(db.Model):
    """Monthly tarot subscription plan."""

    __tablename__ = "subscription_plans"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    minutes_per_month = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Integer, nullable=False)  # monthly price in CLP
    description = db.Column(db.Text, nullable=True)
    features = db.Column(db.Text, nullable=True)  # newline-separated feature list
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_featured = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    def __repr__(self) -> str:
        return f"<SubscriptionPlan {self.name}>"

    @property
    def price_display(self) -> str:
        return f"{self.price:,}".replace(",", ".")

    @property
    def features_list(self) -> list:
        if not self.features:
            return []
        return [f.strip() for f in self.features.splitlines() if f.strip()]


class Product(db.Model):
    """Physical esoteric product (mazos, velas, inciensos, etc.)."""

    __tablename__ = "products"

    CATEGORY_CHOICES = [
        ("mazos", "Mazos de Tarot"),
        ("velas", "Velas"),
        ("inciensos", "Inciensos"),
        ("cristales", "Cristales"),
        ("otros", "Otros"),
    ]

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), unique=True, nullable=False, index=True)
    category = db.Column(db.String(50), nullable=False, default="otros")
    description = db.Column(db.Text, nullable=True)
    price = db.Column(db.Integer, nullable=False)  # price in CLP
    stock = db.Column(db.Integer, nullable=False, default=0)
    image_url = db.Column(db.String(500), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_featured = db.Column(db.Boolean, default=False, nullable=False)
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
        return f"<Product {self.name}>"

    @property
    def price_display(self) -> str:
        return f"{self.price:,}".replace(",", ".")

    @staticmethod
    def make_slug(name: str) -> str:
        return slugify(name)


class Order(db.Model):
    """Customer order (minutes pack, subscription, or physical products)."""

    __tablename__ = "orders"

    STATUS_PENDING = "pending"
    STATUS_PAID = "paid"
    STATUS_FAILED = "failed"
    STATUS_SHIPPED = "shipped"
    STATUS_DELIVERED = "delivered"
    STATUS_CANCELLED = "cancelled"

    id = db.Column(db.Integer, primary_key=True)
    # Optional link to registered user; guests allowed.
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    user = db.relationship("User", backref=db.backref("orders", lazy="dynamic"))

    status = db.Column(db.String(30), nullable=False, default=STATUS_PENDING)
    total = db.Column(db.Integer, nullable=False, default=0)  # CLP
    payment_method = db.Column(db.String(30), nullable=True)  # 'flow' | 'khipu'
    payment_token = db.Column(db.String(255), nullable=True)  # gateway token/order id

    # Shipping details (only required for physical products).
    # Anonymous shipping: unmarked boxes, pickup-point option.
    shipping_name = db.Column(db.String(255), nullable=True)
    shipping_email = db.Column(db.String(255), nullable=True)
    shipping_phone = db.Column(db.String(30), nullable=True)
    shipping_address = db.Column(db.Text, nullable=True)
    shipping_uses_pickup = db.Column(db.Boolean, default=False, nullable=False)
    shipping_pickup_point = db.Column(db.String(255), nullable=True)
    # Anonymous packaging: boxes are sent without branding/markings.
    anonymous_shipping = db.Column(db.Boolean, default=True, nullable=False)

    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    items = db.relationship("OrderItem", backref="order", lazy="dynamic", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Order #{self.id} {self.status}>"

    @property
    def total_display(self) -> str:
        return f"{self.total:,}".replace(",", ".")


class OrderItem(db.Model):
    """A single line item within an Order."""

    __tablename__ = "order_items"

    ITEM_TYPE_MINUTE_PACK = "minute_pack"
    ITEM_TYPE_SUBSCRIPTION = "subscription"
    ITEM_TYPE_PRODUCT = "product"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)
    item_type = db.Column(db.String(20), nullable=False)
    item_id = db.Column(db.Integer, nullable=False)  # FK to the relevant table
    name = db.Column(db.String(255), nullable=False)  # denormalised name
    quantity = db.Column(db.Integer, nullable=False, default=1)
    unit_price = db.Column(db.Integer, nullable=False)  # CLP

    def __repr__(self) -> str:
        return f"<OrderItem {self.name} x{self.quantity}>"

    @property
    def subtotal(self) -> int:
        return self.unit_price * self.quantity

    @property
    def subtotal_display(self) -> str:
        return f"{self.subtotal:,}".replace(",", ".")
