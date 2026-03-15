"""SQLAlchemy models for nuevo-fonotarot."""

import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from flask_security.core import RoleMixin, UserMixin
from flask_merchants.models import PaymentMixin
from slugify import slugify
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

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

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))

    def __repr__(self) -> str:
        return f"<Role {self.name}>"


class User(db.Model, UserMixin):
    """Application user managed by Flask-Security."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(80), unique=True, index=True)
    password: Mapped[str] = mapped_column(String(256), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Required by Flask-Security ≥ 4.0 for token invalidation.
    fs_uniquifier: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    roles = db.relationship(
        "Role", secondary=roles_users, backref=db.backref("users", lazy="dynamic")
    )

    # Customer profile fields ---------------------------------------------------
    # Minimal profile (Known Customer)
    full_name: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(30))
    # Extended profile (Physical Customer - required for physical goods)
    rut: Mapped[str | None] = mapped_column(String(20))
    address: Mapped[str | None] = mapped_column(String(500))
    commune: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    # Preferred payment provider key ('flow' or 'khipu')
    preferred_payment: Mapped[str | None] = mapped_column(String(30))

    def __repr__(self) -> str:
        return f"<User {self.email}>"

    @property
    def has_physical_profile(self) -> bool:
        """Return True when the user has all fields required for physical goods."""
        return all(
            (self.full_name, self.rut, self.address, self.commune, self.postal_code)
        )


class StaticPage(db.Model):
    """A static HTML page served from a configurable URL path.

    The ``content`` field stores raw HTML and is served directly to the
    browser.  When ``template_name`` is set, the view renders that Jinja2
    template (with full homepage context) instead of the raw ``content``.
    Access to create or edit pages must be restricted to trusted
    administrators only.
    """

    __tablename__ = "static_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    path: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    template_name: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
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

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    excerpt: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
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


class OrderStatus(str, enum.Enum):
    """Status values for a customer Order."""

    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class OrderItemType(str, enum.Enum):
    """Item-type discriminator for an OrderItem line."""

    MINUTE_PACK = "minute_pack"
    SUBSCRIPTION = "subscription"
    PRODUCT = "product"


class MinutePack(db.Model):
    """Prepaid tarot-minute package.

    Minutes never expire once purchased.
    """

    __tablename__ = "minute_packs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)  # price in CLP
    description: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
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

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    minutes_per_month: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)  # monthly price in CLP
    description: Mapped[str | None] = mapped_column(Text)
    features: Mapped[str | None] = mapped_column(Text)  # newline-separated feature list
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
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


class ProductCategory(db.Model):
    """Category for physical products.

    Replaces the old hardcoded ``CATEGORY_CHOICES`` list on :class:`Product`.
    """

    __tablename__ = "product_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    def __repr__(self) -> str:
        return f"<ProductCategory {self.slug}>"


class Product(db.Model):
    """Physical esoteric product (mazos, velas, inciensos, etc.)."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    category_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("product_categories.id")
    )
    category = db.relationship(
        "ProductCategory", backref=db.backref("products", lazy="dynamic")
    )
    description: Mapped[str | None] = mapped_column(Text)
    price: Mapped[int] = mapped_column(Integer, nullable=False)  # price in CLP
    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    image_url: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
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


class Order(db.Model, PaymentMixin):
    """Customer order and payment record.

    Extends :class:`~flask_merchants.models.PaymentMixin` so that every order
    also acts as a flask-merchants payment session.  Payment fields
    (``merchants_id``, ``transaction_id``, ``provider``, ``amount``,
    ``currency``, ``state``, etc.) are populated when the checkout is
    initiated via the payment provider.

    ``status`` tracks order-fulfillment milestones (PENDING → PAID → SHIPPED
    → DELIVERED / CANCELLED), while ``state`` (from PaymentMixin) tracks the
    payment-processing lifecycle (pending → succeeded / failed / cancelled).
    """

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Optional link to registered user; guests allowed.
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    user = db.relationship("User", backref=db.backref("orders", lazy="dynamic"))

    # Order fulfillment status (separate from PaymentMixin.state)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=OrderStatus.PENDING
    )
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # CLP integer

    # Shipping details (only required for physical products).
    # Anonymous shipping: unmarked boxes, pickup-point option.
    shipping_name: Mapped[str | None] = mapped_column(String(255))
    shipping_email: Mapped[str | None] = mapped_column(String(255))
    shipping_phone: Mapped[str | None] = mapped_column(String(30))
    shipping_address: Mapped[str | None] = mapped_column(Text)
    shipping_uses_pickup: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    shipping_pickup_point: Mapped[str | None] = mapped_column(String(255))
    # Anonymous packaging: boxes are sent without branding/markings.
    anonymous_shipping: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Override timestamps from PaymentMixin to use Python-side UTC defaults.
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Override PaymentMixin fields that must be nullable before payment is initiated.
    merchants_id: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)
    transaction_id: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)
    provider: Mapped[str | None] = mapped_column(String(64), index=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    currency: Mapped[str | None] = mapped_column(String(3))

    items = db.relationship(
        "OrderItem", backref="order", lazy="dynamic", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Order #{self.id} status={self.status!r} state={self.state!r}>"

    @property
    def total_display(self) -> str:
        return f"{self.total:,}".replace(",", ".")

    def initiate_payment(self, payment_method: str, email: str) -> str:
        """Call the payment provider and populate all payment fields on this order.

        Sets ``merchants_id``, ``transaction_id``, ``provider``, ``amount``,
        ``currency``, ``state``, ``email``, ``request_payload``, and
        ``response_payload`` from the provider response, then commits.

        Returns:
            The provider redirect URL to send the user to.

        Raises:
            Exception: Any provider error is propagated to the caller.
        """
        from flask import url_for

        from .extensions import merchants_ext

        success_url = url_for("tienda.pago_retorno", order_id=self.id, _external=True)
        cancel_url = url_for("tienda.index", _external=True)
        confirmation_url = url_for("tienda.pago_confirmacion", _external=True)

        client = merchants_ext.get_client(payment_method)
        checkout_session = client.payments.create_checkout(
            amount=Decimal(str(self.total)),
            currency="CLP",
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "order_id": str(self.id),
                "confirmation_url": confirmation_url,
                "email": email,
            },
        )

        response_raw = (
            checkout_session.raw if isinstance(checkout_session.raw, dict) else {}
        )
        if checkout_session.redirect_url:
            response_raw.setdefault("redirect_url", checkout_session.redirect_url)

        self.merchants_id = str(uuid.uuid4())
        self.transaction_id = checkout_session.session_id
        self.provider = payment_method
        self.amount = Decimal(str(self.total))
        self.currency = "CLP"
        self.state = "pending"
        self.email = email
        self.request_payload = {
            "order_id": self.id,
            "amount": str(self.total),
            "currency": "CLP",
            "provider": payment_method,
            "confirmation_url": confirmation_url,
        }
        self.response_payload = response_raw

        from .extensions import db as _db

        _db.session.commit()
        return checkout_session.redirect_url

    def to_dict(self) -> dict:
        """Return a dict representation including payment fields.

        Overrides PaymentMixin.to_dict() to guard against None amount
        (before payment is initiated) and include order-specific fields.
        """
        d = {
            "merchants_id": self.merchants_id,
            "transaction_id": self.transaction_id,
            "provider": self.provider,
            "amount": f"{Decimal(str(self.amount)):.2f}" if self.amount is not None else None,
            "currency": self.currency,
            "state": self.state,
            "email": self.email,
            "extra_args": self.extra_args or {},
            "request_payload": self.request_payload or {},
            "response_payload": self.response_payload or {},
            "payment_object": self.payment_object or {},
        }
        d["order_id"] = self.id
        d["order_status"] = self.status
        return d


class OrderItem(db.Model):
    """A single line item within an Order."""

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("orders.id"), nullable=False)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    item_id: Mapped[int] = mapped_column(Integer, nullable=False)  # FK to the relevant table
    name: Mapped[str] = mapped_column(String(255), nullable=False)  # denormalised name
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price: Mapped[int] = mapped_column(Integer, nullable=False)  # CLP

    def __repr__(self) -> str:
        return f"<OrderItem {self.name} x{self.quantity}>"

    @property
    def subtotal(self) -> int:
        return self.unit_price * self.quantity

    @property
    def subtotal_display(self) -> str:
        return f"{self.subtotal:,}".replace(",", ".")


# ---------------------------------------------------------------------------
# Site configuration models
# ---------------------------------------------------------------------------


class SiteSettings(db.Model):
    """Generic key-value store for site-wide configuration.

    Settings are grouped by *module* (e.g. ``"general"``, ``"tienda"``,
    ``"blog"``) so the admin panel can display them in logical sections.

    Notable built-in keys
    ---------------------
    ``available_lang``
        JSON array of available public languages used by the language
        switcher.  Each element is a three-item list::

            [short_code, locale, label]

        Example value::

            [["es","es_CL","Español"],["en","en_US","English"],["pt","pt_BR","Português"]]

        The Tabler flag CSS class is derived automatically from the locale's
        territory code (e.g. ``es_CL`` → ``flag-country-cl``).

    ``dark_hours_start``
        Integer 0-23.  Hour (server local time) at which the dark theme
        becomes the default.  Defaults to ``20`` (8 pm).

    ``dark_hours_end``
        Integer 0-23.  Hour (server local time) at which the light theme
        resumes.  Defaults to ``8`` (8 am).

        Dark window example: start=20, end=8 → dark from 20:00 to 07:59.
    """

    __tablename__ = "site_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    value: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(String(255))
    module: Mapped[str] = mapped_column(String(50), nullable=False, default="general")

    def __repr__(self) -> str:
        return f"<SiteSettings {self.key}={self.value!r}>"

    @classmethod
    def get(cls, key: str, default: str | None = None) -> str | None:
        """Return the value for *key*, or *default* when not found."""
        row = cls.query.filter_by(key=key).first()
        return row.value if row else default

    @classmethod
    def set(
        cls,
        key: str,
        value: str,
        *,
        module: str = "general",
        description: str | None = None,
    ) -> None:
        """Set *value* for *key*, creating the row when it does not exist.

        Commits the current session.
        """
        row = cls.query.filter_by(key=key).first()
        if row is None:
            row = cls(key=key, value=value, module=module, description=description)
            db.session.add(row)
        else:
            row.value = value
        db.session.commit()
