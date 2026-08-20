from typing import Any

import ephem

_EJECUTIVOS_URL = "https://firenze.156.cl/audiotex/ejecutivos"

# Moon phase names in order (index 0–7), matching the template display order.
MOON_PHASE_NAMES = [
    "Luna Nueva",
    "Creciente",
    "Cuarto Creciente",
    "Gibosa Creciente",
    "Luna Llena",
    "Gibosa Menguante",
    "Cuarto Menguante",
    "Menguante",
]


def encrypt_string(msg: str, key: str) -> str:
    from cryptography.fernet import Fernet

    f = Fernet(key.encode())
    return f.encrypt(msg.encode()).decode()


def decrypt_token(token: str, key: str) -> str | None:
    from cryptography.fernet import Fernet, InvalidToken

    try:
        f = Fernet(key.encode())
        return f.encrypt(token.encode()).decode()
    except InvalidToken as e:
        return None


def get_moon_phase_index() -> int:
    """Return the current moon phase as an index from 0 to 7.

    Phases:
        0 - Luna Nueva       (New Moon)
        1 - Creciente        (Waxing Crescent)
        2 - Cuarto Creciente (First Quarter)
        3 - Gibosa Creciente (Waxing Gibbous)
        4 - Luna Llena       (Full Moon)
        5 - Gibosa Menguante (Waning Gibbous)
        6 - Cuarto Menguante (Last Quarter)
        7 - Menguante        (Waning Crescent)

    The position is derived from the fraction of the synodic cycle elapsed
    since the most recent new moon, split into 8 equal segments.
    """
    now = ephem.now()
    prev_new = ephem.previous_new_moon(now)
    next_new = ephem.next_new_moon(now)
    cycle_length = next_new - prev_new  # days (ephem dates subtract to float days)
    elapsed = now - prev_new
    position = elapsed / cycle_length  # 0.0 … <1.0
    return int(position * 8) % 8


def _flag_class(locale: str) -> str:
    """Derive a Tabler flag CSS class from a locale string.

    ``es_CL`` → ``flag-country-cl``
    """
    territory = locale.split("_")[-1].lower()
    return f"flag-country-{territory}"


class _LangEntry:
    """Simple value object exposing the language attributes templates expect."""

    def __init__(self, short: str, locale: str, label: str) -> None:
        self.short = short
        self.locale = locale
        self.label = label
        self.flag_class = _flag_class(locale)

    def __repr__(self) -> str:
        return f"<_LangEntry {self.locale}>"


def _normalize_agent(raw: dict) -> dict:
    """Map a firenze API agent record to the dict shape templates expect.

    Firenze fields:
        nombre      → name
        opcion      → option  (zero-padded string: "01", "15", …)
        ingreso     → logged-in flag
        disponible  → availability flag
        descripcion → description

    Derived:
        number  = "7" + zero-padded opcion  ("7001", "7015", …)
        status  = "available" | "busy" | "offline"
    """
    opcion = int(raw.get("opcion", 0))
    ingreso = bool(raw.get("ingreso", False))
    disponible = bool(raw.get("disponible", False))

    if not ingreso:
        status = "offline"
    elif disponible:
        status = "available"
    else:
        status = "busy"

    return {
        "name": raw.get("nombre", ""),
        "option": f"{opcion:02d}",
        "number": f"7{opcion:03d}",
        "status": status,
        "description": raw.get("descripcion", ""),
    }


_STATUS_ORDER = {"available": 0, "busy": 1, "offline": 2}


def _fetch_order_stats(year: int | None = None, month: int | None = None) -> dict:
    from datetime import date, timedelta

    from sqlalchemy import case, func

    from .extensions import db
    from .models import Order

    PAID_STATUS = "succeeded"
    _MONTHS_ES = {
        1: "Enero",
        2: "Febrero",
        3: "Marzo",
        4: "Abril",
        5: "Mayo",
        6: "Junio",
        7: "Julio",
        8: "Agosto",
        9: "Septiembre",
        10: "Octubre",
        11: "Noviembre",
        12: "Diciembre",
    }

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    if year is not None and month is not None:
        month_start = date(year, month, 1)
        if month == 12:
            month_end = date(year + 1, 1, 1)
        else:
            month_end = date(year, month + 1, 1)
    else:
        month_start = today.replace(day=1)
        month_end = None
    epoch = date(2018, 1, 1)

    paid_case = case((Order.payment_status == PAID_STATUS, 1), else_=0)

    def counts(start, end=None):
        q = db.session.query(
            func.count(Order.id),
            func.coalesce(func.sum(paid_case), 0),
        ).filter(Order.created_at >= start)
        if end:
            q = q.filter(Order.created_at < end)
        total, paid = q.one()
        total, paid = total or 0, int(paid or 0)
        return total, paid, total - paid

    def sales(start, end=None):
        q = db.session.query(func.coalesce(func.sum(Order.amount), 0)).filter(
            Order.payment_status == PAID_STATUS, Order.created_at >= start
        )
        if end:
            q = q.filter(Order.created_at < end)
        return q.scalar() or 0

    def pct_change(current, previous):
        if not previous:
            return None
        return round((current - previous) / previous * 100, 1)

    prev_week_start = week_start - timedelta(days=7)
    if month_start.month == 1:
        prev_month_start = month_start.replace(year=month_start.year - 1, month=12)
    else:
        prev_month_start = month_start.replace(month=month_start.month - 1)
    yesterday = today - timedelta(days=1)

    today_total, today_paid, today_unpaid = counts(today)
    week_total, week_paid, week_unpaid = counts(week_start)
    month_total, month_paid, month_unpaid = counts(month_start, month_end)
    alltime_total, _, _ = counts(epoch)

    today_sales = sales(today)
    week_sales = sales(week_start)
    month_sales = sales(month_start, month_end)
    alltime_sales = sales(epoch)

    return {
        "today": {
            "total": today_total,
            "paid": today_paid,
            "unpaid": today_unpaid,
            "sales": today_sales,
            "sales_pct": pct_change(today_sales, sales(yesterday, today)),
            "label": today.strftime("%d/%m"),
        },
        "week": {
            "total": week_total,
            "paid": week_paid,
            "unpaid": week_unpaid,
            "sales": week_sales,
            "sales_pct": pct_change(week_sales, sales(prev_week_start, week_start)),
            "label": f"{week_start.strftime('%d/%m')} - {today.strftime('%d/%m')}",
        },
        "month": {
            "total": month_total,
            "paid": month_paid,
            "unpaid": month_unpaid,
            "sales": month_sales,
            "sales_pct": pct_change(month_sales, sales(prev_month_start, month_start)),
            "label": _MONTHS_ES[month_start.month].capitalize() + f" {month_start.year}",
        },
        "alltime": {"total": alltime_total, "sales": alltime_sales},
    }


import json
import uuid
from decimal import Decimal

PAID_LEGACY_STATUS = "Pagado"

# Legacy `valor` -> MinutePack.id. Fixed mapping, no DB lookup needed.
LEGACY_PRICE_TO_PACK_ID = {
    Decimal("5000"): 1,
    Decimal("10000"): 2,
    Decimal("30000"): 3,
    Decimal("75000"): 4,
}


def _dashed_uuid(raw_hex: str) -> str:
    """Legacy `transaccion` is a 32-char hex UUID without dashes — reformat properly."""
    return str(uuid.UUID(hex=raw_hex))


def import_legacy_sales(rows, *, dry_run: bool = False) -> dict:
    """Import legacy `zvn_portal` sale rows into Order/OrderItem.

    `rows` is any iterable of dict-like rows (mapping access via `row["col"]`
    / `row.get("col")`) — pass in exactly the batch you want processed;
    pagination is the caller's job (SQL LIMIT/OFFSET), not this function's.

    Idempotent: rows whose merchants_id (derived from `transaccion`) already
    exist as an Order are skipped, so a batch can be safely re-run. Each row
    is wrapped in its own SAVEPOINT so one bad row doesn't roll back the rest.
    """
    from zoneinfo import ZoneInfo

    from .extensions import db
    from .models import MinutePack, Order, OrderItem, OrderItemFulfillmentStatus, OrderItemType, OrderStatus

    pack_ids = set(LEGACY_PRICE_TO_PACK_ID.values())
    packs_by_id = {p.id: p for p in MinutePack.query.filter(MinutePack.id.in_(pack_ids)).all()}
    missing_ids = pack_ids - packs_by_id.keys()
    if missing_ids:
        print(f"WARNING: MinutePack id(s) {sorted(missing_ids)} not found in DB — matching sales will be skipped.")

    stats = {
        "imported": 0,
        "skipped_unpaid": 0,
        "skipped_price": 0,
        "skipped_duplicate": 0,
        "skipped_no_pack": 0,
        "errors": 0,
        "rows_considered": 0,
    }

    for row in rows:
        stats["rows_considered"] += 1

        try:
            if row.get("estado") != PAID_LEGACY_STATUS:
                stats["skipped_unpaid"] += 1
                continue

            valor = Decimal(str(row["valor"]))
            pack_id = LEGACY_PRICE_TO_PACK_ID.get(valor)
            if pack_id is None:
                stats["skipped_price"] += 1
                continue

            pack = packs_by_id.get(pack_id)
            if pack is None:
                stats["skipped_no_pack"] += 1
                continue

            merchants_id = _dashed_uuid(row["transaccion"])

            if db.session.query(Order.id).filter_by(merchants_id=merchants_id).first():
                stats["skipped_duplicate"] += 1
                continue

            if dry_run:
                stats["imported"] += 1
                continue

            utc_created_at = row["creado"].replace(tzinfo=ZoneInfo("UTC"))
            utc_fulfilled_at = row["modificado"].replace(tzinfo=ZoneInfo("UTC"))

            created_at = utc_created_at.astimezone(ZoneInfo("America/Santiago"))
            fulfilled_at = utc_fulfilled_at.astimezone(ZoneInfo("America/Santiago"))
            broker = row.get("broker").split("-")[0]

            with db.session.begin_nested():  # SAVEPOINT — isolates this row's failure
                order = Order(
                    merchants_id=merchants_id,
                    transaction_id=row["broker_pago_id"],
                    provider=broker or "legacy",
                    amount=valor,
                    currency=pack.currency,
                    payment_status="succeeded",
                    email=row.get("correo"),
                    shipping_phone=row.get("telefono") or None,
                    shipping_name=row.get("nombre") or None,
                    status=OrderStatus.DELIVERED,  # verify against your actual OrderStatus values
                    created_at=created_at,
                    request_payload=json.loads(row["broker_payload"]) if row.get("broker_payload") else {},
                    response_payload=json.loads(row["broker_response"]) if row.get("broker_response") else {},
                    firenze_client_id=int(row["client_id"]) if row.get("client_id") else None,
                )
                db.session.add(order)
                db.session.flush()  # populate order.id for the FK below

                item = OrderItem(
                    order_id=order.id,
                    item_type=OrderItemType.MINUTE_PACK,
                    item_id=pack.id,
                    name=f"{pack.minutes} minutos de tarot",
                    quantity=1,
                    unit_price=Decimal(str(pack.price)),
                    currency=pack.currency,
                    fulfillment_status=OrderItemFulfillmentStatus.FULFILLED,
                    fulfilled_at=fulfilled_at,
                    fulfillment_attempts=1,
                    fulfillment_reference=row.get("broker_pago_id"),
                )
                db.session.add(item)
                print(f"{order=} {item=}")
            stats["imported"] += 1

        except Exception as exc:
            stats["errors"] += 1
            print(f"Row transaccion={row.get('transaccion')}: {exc}")
            continue

    if not dry_run:
        db.session.commit()

    return stats


__all__ = [
    "_flag_class",
    "_LangEntry",
    "get_moon_phase_index",
    "MOON_PHASE_NAMES",
]
