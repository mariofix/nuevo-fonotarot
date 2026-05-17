"""SQLAlchemy models for nuevo-fonotarot."""

import enum
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask_security.models import fsqla_v3 as fsqla
from flask_merchants.models import PaymentMixin
from slugify import slugify
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .extensions import db

class Role(db.Model, fsqla.FsRoleMixin):
    """Application role (e.g. 'admin')."""

    __tablename__ = "roles"


    def __repr__(self) -> str:
        return f"<Role {self.name}>"


class User(db.Model, fsqla.FsUserMixin):
    """Application user managed by Flask-Security."""

    __tablename__ = "users"

    
    # Trust window for passwordless signin: if set and current time < trusted_until,
    # user is automatically logged in without requiring email verification.
    trusted_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
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

    # Firenze company-wide client identifier (populated at registration or first purchase).
    firenze_client_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    def __repr__(self) -> str:
        return f"<User {self.email}>"

    @property
    def has_physical_profile(self) -> bool:
        """Return True when the user has all fields required for physical goods."""
        return all(
            (self.full_name, self.rut, self.address, self.commune, self.postal_code)
        )


class WebAuthn(db.Model, fsqla.FsWebAuthnMixin):
    """Stored WebAuthn credentials for a user."""

    __tablename__ = "webauthn"


class StaticPage(db.Model):
    """A static HTML page served from a configurable URL path.

    The ``content`` field stores raw HTML edited via GrapesJS in the admin
    panel.  Setting ``is_homepage = True`` makes this page serve as the site
    homepage (only one page may be the homepage at a time — the admin enforces
    this automatically).  Access to create or edit pages must be restricted to
    trusted administrators only.
    """

    __tablename__ = "static_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    path: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    featured_image_url: Mapped[str | None] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_homepage: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
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
    slug: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    featured_image_url: Mapped[str | None] = mapped_column(String(500))
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

    @property
    def reading_time(self) -> int:
        """Estimated reading time in minutes (200 wpm)."""
        import re
        words = len(re.findall(r"\w+", self.content or ""))
        return max(1, round(words / 200))

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
    price: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # price in CLP (no fractional units)
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
    slug: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    def __repr__(self) -> str:
        return f"<ProductCategory {self.slug}>"


class Product(db.Model):
    """Physical esoteric product (mazos, velas, inciensos, etc.)."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
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
    total: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )  # CLP (no fractional units)

    # Shipping details (only required for physical products).
    # Anonymous shipping: unmarked boxes, pickup-point option.
    shipping_name: Mapped[str | None] = mapped_column(String(255))
    shipping_email: Mapped[str | None] = mapped_column(String(255))
    shipping_phone: Mapped[str | None] = mapped_column(String(30))
    shipping_address: Mapped[str | None] = mapped_column(Text)
    shipping_uses_pickup: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    shipping_pickup_point: Mapped[str | None] = mapped_column(String(255))
    # Anonymous packaging: boxes are sent without branding/markings.
    anonymous_shipping: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

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
    merchants_id: Mapped[str | None] = mapped_column(
        String(128), unique=True, index=True
    )
    transaction_id: Mapped[str | None] = mapped_column(
        String(128), unique=True, index=True
    )
    provider: Mapped[str | None] = mapped_column(String(64), index=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    currency: Mapped[str | None] = mapped_column(String(3))

    # Firenze company-wide client identifier (linked after lookup or confirmed payment).
    firenze_client_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

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
        from flask import current_app, url_for

        from .extensions import merchants_ext

        currency = SiteSettings.get(
            "default_currency", current_app.config.get("DEFAULT_CURRENCY", "CLP")
        )
        confirmation_url = url_for("pagos.pago_confirmacion", _external=True)
        cancel_url = url_for("content.index", _external=True, _anchor="planes")

        # Generate merchants_id before building URLs so it can be used in success_url.
        merchants_id = str(uuid.uuid4())

        success_url = url_for(
            "pagos.pago_retorno", order_id=merchants_id, _external=True
        )

        # Build extra_args (provider-specific kwargs) mirroring PaymentMixin.create().
        # Stored in self.extra_args for audit and unpacked into create_checkout(**kwargs).
        # Each provider only receives the kwargs it understands.
        extra_args: dict = {}
        if payment_method == "khipu":
            # Khipu accepts payer_email to pre-fill the payer's email field.
            extra_args["payer_email"] = email
        elif payment_method == "flow":
            # Flow requires email as a first-class field; payer_email is not valid.
            # Optionally restrict accepted payment methods (e.g. webpay only).
            flow_payment_method = current_app.config.get("FLOW_PAYMENT_METHOD")
            if flow_payment_method:
                extra_args["paymentMethod"] = flow_payment_method

        # Auto-inject notify_url via the public registry (not client._provider).
        import merchants as _merchants_registry

        try:
            provider_obj = _merchants_registry.get_provider(payment_method)
            if getattr(provider_obj, "accepts_notify_url", False):
                try:
                    extra_args.setdefault(
                        "notify_url", merchants_ext.get_webhook_url(payment_method)
                    )
                except RuntimeError:
                    pass
        except (KeyError, RuntimeError):
            pass
        client = merchants_ext.get_client(payment_method)

        try:
            checkout_session = client.payments.create_checkout(
                amount=int(self.total),
                currency=currency,
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "order_id": merchants_id,
                    "confirmation_url": confirmation_url,
                    "email": email,
                },
                **extra_args,
            )
        except Exception as exc:
            # Extract the API response body before re-raising so the real
            # error is visible in the logs.
            if exc.args and isinstance(exc.args[0], dict):
                response_obj = exc.args[0].get("message")
                body = getattr(response_obj, "text", None)
                if body:
                    import logging as _logging

                    _logging.getLogger(__name__).error(
                        "Payment API error [provider=%s code=%s]: %s",
                        payment_method,
                        exc.args[0].get("code"),
                        body,
                    )
            raise RuntimeError(f"Payment gateway error from {payment_method}") from exc

        response_raw = (
            checkout_session.raw if isinstance(checkout_session.raw, dict) else {}
        )
        if checkout_session.redirect_url:
            response_raw.setdefault("redirect_url", checkout_session.redirect_url)

        self.merchants_id = merchants_id
        self.transaction_id = checkout_session.session_id
        self.provider = payment_method
        self.amount = Decimal(str(self.total))
        self.currency = currency
        self.state = OrderStatus.PENDING
        self.email = email
        self.extra_args = extra_args
        self.request_payload = {
            "order_id": self.id,
            "amount": str(self.total),
            "currency": currency,
            "provider": payment_method,
            "confirmation_url": confirmation_url,
            **extra_args,
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
            "amount": (
                f"{Decimal(str(self.amount)):.2f}" if self.amount is not None else None
            ),
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
    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orders.id"), nullable=False
    )
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    item_id: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # FK to the relevant table
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
    ``dark_hours_start``
        Integer 0-23.  Hour (server local time) at which the dark theme
        becomes the default.  Defaults to ``20`` (8 pm).

    ``dark_hours_end``
        Integer 0-23.  Hour (server local time) at which the light theme
        resumes.  Defaults to ``8`` (8 am).

        Dark window example: start=20, end=8 → dark from 20:00 to 07:59.

    Analytics keys  (module ``"analytics"``)
    -----------------------------------------
    ``umami_website_id``
        Umami website ID shown in the Umami dashboard (e.g. ``"abc123-..."``).
        Leave empty or absent to disable the Umami web tracker.

    ``umami_email_pixel_id``
        Token that appears after ``/p/`` in the Umami email pixel URL.
        Leave empty or absent to omit the 1×1 tracking pixel from emails.

    ``gtm_container_id``
        Google Tag Manager container ID (e.g. ``"GTM-XXXXXXX"``).
        Leave empty or absent to disable GTM.

    ``ga_measurement_id``
        Google Analytics 4 measurement ID (e.g. ``"G-XXXXXXXXXX"``).
        Not required when GTM already injects GA4.
        Leave empty or absent to disable direct GA4 loading.

    ``meta_pixel_id``
        Meta (Facebook) Pixel ID (e.g. ``"1234567890"``).
        Leave empty or absent to disable the Meta Pixel.

    ``segment_write_key``
        Twilio Segment source write key.  Segment acts as a tag manager and
        can forward events to many downstream destinations.
        Leave empty or absent to disable Segment.

    SEO keys  (module ``"seo"``)
    ----------------------------
    ``seo_site_title``
        Default ``<title>`` and og:title / twitter:title fallback.

    ``seo_site_description``
        Default meta description, og:description, and twitter:description fallback.

    ``seo_site_keywords``
        Default meta keywords (comma-separated).

    ``seo_site_author``
        Value for the ``author`` meta tag.

    ``seo_copyright``
        Value for the ``copyright`` meta tag.

    ``seo_robots``
        Content for ``robots``, ``googlebot``, and ``bingbot`` meta tags.
        Defaults to ``"index, follow, max-snippet:-1, max-image-preview:large, max-video-preview:-1"``.

    ``seo_language``
        Value for the ``language`` meta tag, e.g. ``"Spanish"``.

    ``seo_geo_region``
        ISO region code for the ``geo.region`` meta tag, e.g. ``"CL"``.

    ``seo_geo_country``
        Country name for the ``geo.country`` meta tag, e.g. ``"Chile"``.

    ``seo_geo_placename``
        City or place name for the ``geo.placename`` meta tag.

    ``seo_og_site_name``
        ``og:site_name`` value shown when pages are shared on social networks.

    ``seo_og_image_url``
        Absolute URL for the default ``og:image`` and ``twitter:image``.
        Falls back to ``/static/og-image.jpg`` when absent.

    ``seo_twitter_handle``
        Twitter/X account handle without ``@``.  Used for both ``twitter:site``
        and ``twitter:creator``.

    ``seo_google_verification``
        Content value for the ``google-site-verification`` meta tag
        (Google Search Console).  Tag is omitted when empty.

    ``seo_bing_verification``
        Content value for the ``msvalidate.01`` meta tag
        (Bing Webmaster Tools).  Tag is omitted when empty.

    ``seo_twitter_card``
        Twitter card type: ``"summary_large_image"`` (default) or ``"summary"``.

    ``seo_app_title``
        Short name for ``apple-mobile-web-app-title`` (shown under the icon on iOS).
        ``apple-mobile-web-app-status-bar-style`` is derived automatically from
        the active theme (``dark`` → ``black-translucent``, ``light`` → ``default``).

    ``seo_theme_color_light``
        Hex colour for ``theme-color`` in light mode (``prefers-color-scheme: light``).

    ``seo_theme_color_dark``
        Hex colour for ``theme-color`` in dark mode (``prefers-color-scheme: dark``).

    ``seo_tile_color``
        Hex colour for ``msapplication-TileColor`` and ``msapplication-navbutton-color``.
    """

    __tablename__ = "site_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(
        String(80), unique=True, nullable=False, index=True
    )
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
    def bulk_get(
        cls, keys: list[str], defaults: dict[str, str] | None = None
    ) -> dict[str, str | None]:
        """Return values for all *keys* in a single query.

        Missing keys resolve to the value in *defaults* (if provided)
        or ``None``.
        """
        defaults = defaults or {}
        rows = cls.query.filter(cls.key.in_(keys)).all()
        found = {row.key: row.value for row in rows}
        return {key: found.get(key) or defaults.get(key) for key in keys}

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
