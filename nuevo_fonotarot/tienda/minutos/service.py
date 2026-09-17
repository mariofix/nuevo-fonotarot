"""Domain services for minute-pack pricing."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from babel.numbers import format_currency as babel_format_currency
from flask_babel import _, get_locale
from sqlalchemy import and_
from sqlalchemy.orm import selectinload

from ...models import MinutePack, MinutePackRolePrice, Order, OrderItem, OrderItemType, OrderStatus


@dataclass(frozen=True)
class ResolvedMinutePackPrice:
    """Resolved minute-pack price for a specific user and instant."""

    amount: Decimal
    currency: str
    base_amount: Decimal
    base_currency: str
    applied_role_name: str | None = None
    schedule_id: int | None = None
    starts_at: datetime | None = None

    @property
    def display(self) -> str:
        """Return the resolved price formatted for the active locale."""
        return babel_format_currency(self.amount, self.currency, locale=get_locale(), format="#,##0.0 ¤¤")

    @property
    def base_display(self) -> str:
        """Return the base pack price formatted for the active locale."""
        return babel_format_currency(self.base_amount, self.base_currency, locale=get_locale(), format="#,##0.0 ¤¤")

    @property
    def is_overridden(self) -> bool:
        """Return True when a role-specific override was applied."""
        return self.schedule_id is not None


def minute_pack_pricing_query():
    """Return a MinutePack query with role-pricing relationships preloaded."""
    return MinutePack.query.options(
        selectinload(MinutePack.role_prices).selectinload(MinutePackRolePrice.role),
    )


def get_active_minute_packs() -> list[MinutePack]:
    """Return active minute packs with pricing schedules preloaded."""
    return minute_pack_pricing_query().filter_by(is_active=True).order_by(MinutePack.minutes).all()


def get_active_minute_pack_by_slug(pack_slug: str) -> MinutePack:
    """Return one active minute pack by slug with pricing schedules preloaded."""
    return minute_pack_pricing_query().filter_by(slug=pack_slug, is_active=True).first_or_404()


def resolve_minute_pack_price(
    pack: MinutePack,
    user=None,
    at: datetime | None = None,
) -> ResolvedMinutePackPrice:
    """Return the effective price for *pack* for the supplied user."""
    base_resolved = _base_resolved_price(pack)
    now = at or datetime.now()

    if not getattr(user, "is_authenticated", False):
        return base_resolved

    role_ids = {role.id for role in list(getattr(user, "roles", [])) if getattr(role, "id", None) is not None}
    if not role_ids:
        return base_resolved

    applicable_by_role: dict[int, MinutePackRolePrice] = {}
    for candidate in list(getattr(pack, "role_prices", [])):
        if not candidate.is_active or candidate.role_id not in role_ids:
            continue
        if candidate.currency != base_resolved.base_currency:
            continue
        if candidate.starts_at > now:
            continue
        current = applicable_by_role.get(candidate.role_id)
        if current is None or _schedule_sort_key(candidate) > _schedule_sort_key(current):
            applicable_by_role[candidate.role_id] = candidate

    if not applicable_by_role:
        return base_resolved

    selected = min(
        applicable_by_role.values(),
        key=lambda candidate: (
            Decimal(str(candidate.price)),
            -_schedule_timestamp_key(candidate.starts_at),
            getattr(candidate.role, "name", ""),
            candidate.id or 0,
        ),
    )
    return ResolvedMinutePackPrice(
        amount=Decimal(str(selected.price)),
        currency=selected.currency,
        base_amount=base_resolved.base_amount,
        base_currency=base_resolved.base_currency,
        applied_role_name=getattr(selected.role, "name", None),
        schedule_id=selected.id,
        starts_at=selected.starts_at,
    )


def summarize_current_role_prices(pack: MinutePack, at: datetime | None = None) -> str:
    """Return a compact summary of currently active role prices for a pack."""
    current_by_role = _current_role_prices(pack, at)
    if not current_by_role:
        return _("Sin precios leales activos")
    parts = []
    for role_name, schedule in sorted(current_by_role.items()):
        display = babel_format_currency(
            Decimal(str(schedule.price)),
            schedule.currency,
            locale=get_locale(),
            format="#,##0.0 ¤¤",
        )
        parts.append(_("%(role)s: %(price)s", role=role_name, price=display))
    return ", ".join(parts)


def find_pending_minute_pack_order(
    *,
    pack_id: int,
    amount: Decimal,
    provider: str,
    email: str,
    duplicate_cutoff: datetime,
    user_id: int | None,
):
    """Return a matching pending minute-pack order created recently, if any."""
    duplicate_filter = and_(
        OrderItem.item_type == OrderItemType.MINUTE_PACK,
        OrderItem.item_id == pack_id,
    )
    query = (
        Order.query.filter(
            Order.status == OrderStatus.PENDING,
            Order.provider == provider,
            Order.amount == amount,
            Order.shipping_email == email,
            Order.created_at >= duplicate_cutoff,
            Order.items.any(duplicate_filter),
        )
        .order_by(Order.created_at.desc())
    )
    if user_id is None:
        query = query.filter(Order.user_id.is_(None))
    else:
        query = query.filter(Order.user_id == user_id)
    return query.first()


def _base_resolved_price(pack: MinutePack) -> ResolvedMinutePackPrice:
    base_amount = Decimal(str(pack.price))
    return ResolvedMinutePackPrice(
        amount=base_amount,
        currency=pack.currency,
        base_amount=base_amount,
        base_currency=pack.currency,
    )


def _current_role_prices(pack: MinutePack, at: datetime | None = None) -> dict[str, MinutePackRolePrice]:
    now = at or datetime.now()
    current_by_role: dict[str, MinutePackRolePrice] = {}
    for candidate in list(getattr(pack, "role_prices", [])):
        if not candidate.is_active or candidate.starts_at > now:
            continue
        role_name = getattr(candidate.role, "name", "")
        if not role_name:
            continue
        current = current_by_role.get(role_name)
        if current is None or _schedule_sort_key(candidate) > _schedule_sort_key(current):
            current_by_role[role_name] = candidate
    return current_by_role


def _schedule_sort_key(candidate: MinutePackRolePrice) -> tuple[float, int]:
    return (_schedule_timestamp_key(candidate.starts_at), candidate.id or 0)


def _schedule_timestamp_key(value: datetime | None) -> float:
    if value is None:
        return float("-inf")
    return value.timestamp()
