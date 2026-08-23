"""Flask-Admin configuration using Flask-Security for authentication."""

import json
import os
from datetime import date, datetime, timedelta

import requests
from flask import current_app, jsonify, redirect, request, url_for
from flask_admin import AdminIndexView, BaseView, expose
from flask_admin.actions import action
from flask_admin.contrib.fileadmin import FileAdmin
from flask_admin.contrib.sqla import ModelView
from flask_admin.menu import MenuLink
from flask_admin.model.template import EndpointLinkRowAction
from flask_babel import lazy_gettext as _l
from flask_security import current_user
from sqlalchemy import func

from .extensions import db

# Spanish month names used in legacy CDR report views
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


class SecureAdminIndexView(AdminIndexView):
    """Admin index view that requires an authenticated user with the 'admin' role."""

    PAID_STATUS = "succeeded"

    # Bucket-size thresholds, in days of visible range. Tune to taste.
    GRANULARITY_THRESHOLDS = (
        (15, "week"),  # visible span > 15 days -> weekly buckets
        (2, "day"),  # 2-15 days -> daily buckets
        (0, "hour"),  # < 2 days -> hourly buckets
    )

    def is_accessible(self):
        return current_user and current_user.is_authenticated and current_user.has_role("admin")

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for("security.login", next=request.url))

    @staticmethod
    def _pick_granularity(span_days: float) -> str:
        for threshold, granularity in SecureAdminIndexView.GRANULARITY_THRESHOLDS:
            if span_days > threshold:
                return granularity
        return "hour"

    @staticmethod
    def _bucket_expr(granularity: str):
        from .models import Order

        if granularity == "hour":
            return func.date_format(Order.created_at, "%Y-%m-%d %H:00:00")
        if granularity == "day":
            return func.date(Order.created_at)
        if granularity == "week":
            # Monday of the ISO week, via MariaDB's SUBDATE/WEEKDAY
            return func.subdate(func.date(Order.created_at), func.weekday(Order.created_at))
        raise ValueError(f"Unknown granularity: {granularity}")

    @staticmethod
    def _merchant_token() -> str:
        from itsdangerous import URLSafeTimedSerializer

        serializer = URLSafeTimedSerializer(current_app.config["MERCHANTS_KEY"], salt="fonotarot.merchants.internal")
        return serializer.dumps({"scope": "orders-summary"})

    @staticmethod
    def _merge_series_points(local_series: list[dict], remote_series: list[dict]) -> list[dict]:
        by_x: dict[int, float] = {}
        for point in local_series + remote_series:
            x = point.get("x")
            y = point.get("y", 0) or 0
            if x is None:
                continue
            by_x[int(x)] = by_x.get(int(x), 0.0) + float(y)
        return [{"x": x, "y": y} for x, y in sorted(by_x.items())]

    @staticmethod
    def _merge_catalog_rows(local_rows: list[dict], remote_rows: list[dict], key_field: str) -> list[dict]:
        merged: dict[str, dict] = {}
        numeric_fields = {
            "month_qty",
            "total_qty",
            "month_revenue",
            "total_revenue",
            "discounted_amount",
            "month_amount",
            "total_amount",
            "uses",
            "month_uses",
            "redeemed_count",
            "issued_count",
            "qty",
            "amount",
            "revenue",
        }
        for row in [*local_rows, *remote_rows]:
            key = str(row.get(key_field))
            if not key:
                continue
            if key not in merged:
                merged[key] = dict(row)
                continue
            for numeric_field in numeric_fields:
                if numeric_field not in row:
                    continue
                merged[key][numeric_field] = float(merged[key].get(numeric_field, 0) or 0) + float(row.get(numeric_field, 0) or 0)
            for field in ("name", "code", "provider", "currency", "item_id"):
                if field in row and not merged[key].get(field):
                    merged[key][field] = row.get(field)
        return list(merged.values())

    @staticmethod
    def _fetch_remote_orders_summary(endpoint: str) -> dict | None:
        merchant_key = current_app.config.get("MERCHANTS_KEY")
        if not merchant_key or merchant_key in {"dev-merchants-key-change-me", "change-me-to-a-shared-random-secret"}:
            return None

        token = SecureAdminIndexView._merchant_token()
        try:
            response = requests.get(
                endpoint,
                headers={"Authorization": "Bearer " + token},
                timeout=5,
            )
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return payload
        except (requests.RequestException, ValueError):
            return None
        return None

    def _build_sales_series(self, start_dt: datetime, end_dt: datetime, granularity: str) -> list[dict]:
        from .models import Order

        bucket = self._bucket_expr(granularity).label("bucket")
        rows = (
            db.session.query(bucket, func.coalesce(func.sum(Order.amount), 0).label("total"))
            .filter(
                Order.payment_status == self.PAID_STATUS,
                Order.created_at >= start_dt,
                Order.created_at < end_dt,
            )
            .group_by(bucket)
            .order_by(bucket)
            .all()
        )

        def to_ms(value) -> int:
            if isinstance(value, datetime):
                return int(value.timestamp() * 1000)
            if isinstance(value, str):
                return int(datetime.strptime(value, "%Y-%m-%d %H:%M:%S").timestamp() * 1000)
            return int(datetime(value.year, value.month, value.day).timestamp() * 1000)

        return [{"x": to_ms(r.bucket), "y": float(r.total)} for r in rows]

    @expose("/api/sales-series")
    def sales_series(self):
        import math

        now = datetime.now()
        try:
            start_ms = request.args.get("start", type=float)
            end_ms = request.args.get("end", type=float)

            if start_ms is not None and not math.isfinite(start_ms):
                start_ms = None
            if end_ms is not None and not math.isfinite(end_ms):
                end_ms = None

            start_dt = (
                datetime.fromtimestamp(start_ms / 1000)
                if start_ms
                else now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            )
            end_dt = datetime.fromtimestamp(end_ms / 1000) if end_ms else now
        except (TypeError, ValueError, OSError):
            return jsonify({"error": "invalid start/end"}), 400

        if end_dt <= start_dt:
            return jsonify({"error": "end must be after start"}), 400

        span_days = (end_dt - start_dt).total_seconds() / 86400
        granularity = request.args.get("granularity")
        if not granularity:
            granularity = "day" if start_ms is None and end_ms is None else self._pick_granularity(span_days)

        series = self._build_sales_series(start_dt, end_dt, granularity)
        for endpoint in current_app.config.get("MERCHANTS_EXTERNAL_ENDPOINTS", []):
            payload = self._fetch_remote_orders_summary(endpoint)
            if not payload:
                continue
            remote_series = payload.get("sales_series", {}).get("series", [])
            if remote_series:
                series = self._merge_series_points(series, remote_series)

        return jsonify({"granularity": granularity, "series": series})

    def _catalog_stats_payload(self, year: int | None = None, month: int | None = None) -> dict:
        """Return raw storefront sales aggregates suitable for internal federation."""
        from .models import DiscountCode, GiftCard, GiftCardProduct, MinutePack, Order, OrderItem, OrderItemType

        if year and month:
            month_start = date(year, month, 1)
            if month == 12:
                month_end = date(year + 1, 1, 1)
            else:
                month_end = date(year, month + 1, 1)
        else:
            today = date.today()
            month_start = today.replace(day=1)
            month_end = None

        def _pack_sales(since=None, until=None):
            subtotal = OrderItem.unit_price * OrderItem.quantity
            q = (
                db.session.query(
                    OrderItem.item_id,
                    func.coalesce(func.sum(OrderItem.quantity), 0),
                    func.coalesce(func.sum(subtotal), 0),
                )
                .join(Order, Order.id == OrderItem.order_id)
                .filter(OrderItem.item_type == OrderItemType.MINUTE_PACK, Order.payment_status == self.PAID_STATUS)
            )
            if since:
                q = q.filter(Order.created_at >= since)
            if until:
                q = q.filter(Order.created_at < until)
            rows = q.group_by(OrderItem.item_id).all()
            return {item_id: {"qty": qty, "revenue": revenue} for item_id, qty, revenue in rows}

        pack_month_sales = _pack_sales(since=month_start, until=month_end)
        pack_total_sales = _pack_sales()
        packs = MinutePack.query.filter_by(is_active=True).order_by(MinutePack.minutes).all()
        minute_packs = [
            {
                "key": f"minute_pack:{p.id}",
                "item_id": p.id,
                "name": f"{p.minutes} Minutos",
                "currency": p.currency,
                "is_featured": p.is_featured,
                "month_qty": pack_month_sales.get(p.id, {}).get("qty", 0),
                "total_qty": pack_total_sales.get(p.id, {}).get("qty", 0),
                "month_revenue": pack_month_sales.get(p.id, {}).get("revenue", 0),
                "total_revenue": pack_total_sales.get(p.id, {}).get("revenue", 0),
            }
            for p in packs
        ]

        def _giftcard_sales(since=None, until=None):
            subtotal = OrderItem.unit_price * OrderItem.quantity
            q = (
                db.session.query(
                    OrderItem.item_id,
                    func.coalesce(func.sum(OrderItem.quantity), 0),
                    func.coalesce(func.sum(subtotal), 0),
                )
                .join(Order, Order.id == OrderItem.order_id)
                .filter(OrderItem.item_type == OrderItemType.GIFT_CARD, Order.payment_status == self.PAID_STATUS)
            )
            if since:
                q = q.filter(Order.created_at >= since)
            if until:
                q = q.filter(Order.created_at < until)
            rows = q.group_by(OrderItem.item_id).all()
            return {item_id: {"qty": qty, "revenue": revenue} for item_id, qty, revenue in rows}

        gc_month_sales = _giftcard_sales(since=month_start, until=month_end)
        gc_total_sales = _giftcard_sales()
        gc_redeemed = dict(
            db.session.query(GiftCard.gift_card_product_id, func.count(GiftCard.id))
            .filter(GiftCard.status == "redeemed")
            .group_by(GiftCard.gift_card_product_id)
            .all()
        )
        gc_products = GiftCardProduct.query.filter_by(is_active=True).order_by(GiftCardProduct.minutes).all()
        gift_cards = []
        for gp in gc_products:
            month_qty = gc_month_sales.get(gp.id, {}).get("qty", 0)
            total_qty = gc_total_sales.get(gp.id, {}).get("qty", 0)
            redeemed = gc_redeemed.get(gp.id, 0)
            gift_cards.append(
                {
                    "key": f"gift_card:{gp.id}",
                    "item_id": gp.id,
                    "name": gp.name,
                    "currency": gp.currency,
                    "is_featured": gp.is_featured,
                    "month_qty": month_qty,
                    "total_qty": total_qty,
                    "month_revenue": gc_month_sales.get(gp.id, {}).get("revenue", 0),
                    "total_revenue": gc_total_sales.get(gp.id, {}).get("revenue", 0),
                    "redeemed_count": redeemed,
                    "issued_count": total_qty,
                }
            )

        codes = DiscountCode.query.order_by(DiscountCode.uses_count.desc()).limit(10).all()
        q_discount = db.session.query(
            Order.discount_code_id, func.coalesce(func.sum(Order.discount_amount), 0)
        ).filter(
            Order.discount_code_id.isnot(None),
            Order.discount_amount.isnot(None),
            Order.payment_status == self.PAID_STATUS,
        )
        if year and month:
            q_discount = q_discount.filter(Order.created_at >= month_start, Order.created_at < month_end)
        discount_totals = dict(q_discount.group_by(Order.discount_code_id).all())
        q_discount_count = db.session.query(Order.discount_code_id, func.count(Order.id)).filter(
            Order.discount_code_id.isnot(None),
            Order.payment_status == self.PAID_STATUS,
        )
        if year and month:
            q_discount_count = q_discount_count.filter(Order.created_at >= month_start, Order.created_at < month_end)
        discount_month_uses = dict(q_discount_count.group_by(Order.discount_code_id).all())
        discount_codes = [
            {
                "key": f"discount_code:{c.id}",
                "code": c.code,
                "currency": c.currency or "CLP",
                "uses": c.uses_count,
                "month_uses": discount_month_uses.get(c.id, 0),
                "max_uses": c.max_uses,
                "discounted_amount": discount_totals.get(c.id, 0),
            }
            for c in codes
        ]

        def _provider_sales(since=None, until=None):
            q = db.session.query(
                Order.provider,
                func.coalesce(func.count(Order.id), 0),
                func.coalesce(func.sum(Order.amount), 0),
            ).filter(Order.payment_status == self.PAID_STATUS)
            if since:
                q = q.filter(Order.created_at >= since)
            if until:
                q = q.filter(Order.created_at < until)
            rows = q.group_by(Order.provider).all()
            return {provider: {"qty": qty, "amount": amount} for provider, qty, amount in rows}

        provider_month_sales = _provider_sales(since=month_start, until=month_end)
        provider_total_sales = _provider_sales()
        pay_providers = [
            {
                "key": f"provider:{provider or 'unknown'}",
                "provider": provider or "—",
                "month_qty": provider_month_sales.get(provider, {}).get("qty", 0),
                "total_qty": provider_total_sales.get(provider, {}).get("qty", 0),
                "month_amount": provider_month_sales.get(provider, {}).get("amount", 0),
                "total_amount": provider_total_sales.get(provider, {}).get("amount", 0),
            }
            for provider in sorted(set(provider_month_sales) | set(provider_total_sales), key=lambda p: provider_total_sales.get(p, {}).get("amount", 0), reverse=True)
        ]
        return {
            "minute_packs": minute_packs,
            "gift_cards": gift_cards,
            "discount_codes": discount_codes,
            "pay_providers": pay_providers,
        }

    def _fetch_catalog_stats(self, year: int | None = None, month: int | None = None) -> dict:
        """Real sales figures for MinutePacks, GiftCardProducts, and DiscountCodes,
        replacing the hardcoded dashboard table rows."""
        from flask_babel import format_currency

        local_stats = self._catalog_stats_payload(year=year, month=month)
        remote_stats = []
        for endpoint in current_app.config.get("MERCHANTS_EXTERNAL_ENDPOINTS", []):
            payload = self._fetch_remote_orders_summary(endpoint)
            if not payload:
                continue
            remote_stats.append(payload.get("catalog_stats", {}))

        if remote_stats:
            merged = {
                "minute_packs": self._merge_catalog_rows(local_stats.get("minute_packs", []), remote_stats[0].get("minute_packs", []), "key"),
                "gift_cards": self._merge_catalog_rows(local_stats.get("gift_cards", []), remote_stats[0].get("gift_cards", []), "key"),
                "discount_codes": self._merge_catalog_rows(local_stats.get("discount_codes", []), remote_stats[0].get("discount_codes", []), "key"),
                "pay_providers": self._merge_catalog_rows(local_stats.get("pay_providers", []), remote_stats[0].get("pay_providers", []), "key"),
            }
            for extra_payload in remote_stats[1:]:
                merged["minute_packs"] = self._merge_catalog_rows(merged.get("minute_packs", []), extra_payload.get("minute_packs", []), "key")
                merged["gift_cards"] = self._merge_catalog_rows(merged.get("gift_cards", []), extra_payload.get("gift_cards", []), "key")
                merged["discount_codes"] = self._merge_catalog_rows(merged.get("discount_codes", []), extra_payload.get("discount_codes", []), "key")
                merged["pay_providers"] = self._merge_catalog_rows(merged.get("pay_providers", []), extra_payload.get("pay_providers", []), "key")
        else:
            merged = local_stats

        minute_pack_rows = []
        if merged.get("minute_packs"):
            total_pack_month_revenue = sum(float(item.get("month_revenue", 0) or 0) for item in merged["minute_packs"]) or 1
            colors = ["primary", "indigo", "cyan", "pink", "lime", "azure", "orange", "teal", "indigo"]
            for item in merged["minute_packs"]:
                month_revenue = float(item.get("month_revenue", 0) or 0)
                minute_pack_rows.append(
                    {
                        "name": item.get("name", ""),
                        "color": colors.pop(),
                        "is_featured": item.get("is_featured", False),
                        "month_qty": int(item.get("month_qty", 0) or 0),
                        "total_qty": int(item.get("total_qty", 0) or 0),
                        "month_revenue_display": format_currency(month_revenue, item.get("currency", "CLP")),
                        "total_revenue_display": format_currency(float(item.get("total_revenue", 0) or 0), item.get("currency", "CLP")),
                        "width_pct": round((month_revenue / total_pack_month_revenue) * 100, 1) if total_pack_month_revenue else 0,
                    }
                )

        gift_cards = merged.get("gift_cards", [])
        total_gc_month_revenue = sum(float(item.get("month_revenue", 0) or 0) for item in gift_cards) or 1
        gift_card_rows = []
        colors = ["lime", "cyan", "pink", "azure", "orange", "teal", "indigo"]
        for item in gift_cards:
            total = int(item.get("total_qty", 0) or 0)
            redeemed = int(item.get("redeemed_count", 0) or 0)
            month_revenue = float(item.get("month_revenue", 0) or 0)
            gift_card_rows.append(
                {
                    "name": item.get("name", ""),
                    "is_featured": item.get("is_featured", False),
                    "color": colors.pop(0),
                    "month_qty": int(item.get("month_qty", 0) or 0),
                    "total_qty": total,
                    "pct_used": round(redeemed / total * 100, 1) if total else None,
                    "month_revenue_display": format_currency(month_revenue, item.get("currency", "CLP")),
                    "width_pct": round((month_revenue / total_gc_month_revenue) * 100, 1) if total_gc_month_revenue else 0,
                }
            )

        discount_codes = merged.get("discount_codes", [])
        max_uses_seen = max((int(item.get("uses", 0) or 0) for item in discount_codes), default=0) or 1
        colors = ["orange", "pink", "azure", "orange", "teal", "indigo", "blue", "purple", "success", "danger"]
        discount_rows = []
        for item in discount_codes:
            uses = int(item.get("uses", 0) or 0)
            max_uses = item.get("max_uses")
            if max_uses:
                pct = round(uses / max_uses * 100, 1)
                width = min(pct, 100.0)
            else:
                pct = None
                width = round(uses / max_uses_seen * 100, 1)
            discount_rows.append(
                {
                    "code": item.get("code", ""),
                    "uses": uses,
                    "month_uses": int(item.get("month_uses", 0) or 0),
                    "max_uses": max_uses,
                    "pct": pct,
                    "width_pct": width,
                    "discounted_display": format_currency(float(item.get("discounted_amount", 0) or 0), item.get("currency", "CLP")),
                    "color": colors.pop(),
                }
            )

        pay_provider_rows = []
        provider_month_sales = {
            item.get("provider", "—"): {"qty": int(item.get("month_qty", 0) or 0), "amount": float(item.get("month_amount", 0) or 0)}
            for item in merged.get("pay_providers", [])
        }
        total_month_amount = sum(v["amount"] for v in provider_month_sales.values()) or 1
        colors = ["primary", "indigo", "cyan", "pink", "lime", "azure", "orange", "teal", "indigo"]
        for item in merged.get("pay_providers", []):
            provider = item.get("provider", "—")
            month_amount = float(item.get("month_amount", 0) or 0)
            pay_provider_rows.append(
                {
                    "name": provider,
                    "month_qty": int(item.get("month_qty", 0) or 0),
                    "month_amount_display": format_currency(month_amount, "CLP"),
                    "total_qty": int(item.get("total_qty", 0) or 0),
                    "total_amount_display": format_currency(float(item.get("total_amount", 0) or 0), "CLP"),
                    "width_pct": round((month_amount / total_month_amount) * 100, 1) if total_month_amount else 0,
                    "color": colors.pop(),
                }
            )

        return {
            "minute_packs": minute_pack_rows,
            "gift_cards": gift_card_rows,
            "discount_codes": discount_rows,
            "pay_providers": pay_provider_rows,
        }

    @expose("/")
    def index(self):
        today = date.today()
        latest_data = None
        latest_error = None
        agent_data = None
        agent_error = None
        order_stats = None
        order_stats_error = None
        catalog_stats = None
        catalog_stats_error = None
        try:
            from .legacy.views import _fetch_monthly_3carrier

            latest_data = _fetch_monthly_3carrier(today.year, today.month)
        except Exception as exc:
            latest_error = str(exc)
        try:
            from .legacy.views import _fetch_all_agents_monthly_cdr

            agent_data = _fetch_all_agents_monthly_cdr(today.year, today.month)
        except Exception as exc:
            agent_error = str(exc)
        try:
            from .utils import _fetch_order_stats

            order_stats = _fetch_order_stats()
        except Exception as exc:
            order_stats_error = str(exc)
        try:
            catalog_stats = self._fetch_catalog_stats()
        except Exception as exc:
            catalog_stats_error = str(exc)

        return self.render(
            "admin/index.html",
            latest_year=today.year,
            latest_month=today.month,
            months_es=_MONTHS_ES,
            latest_data=latest_data,
            latest_error=latest_error,
            agent_data=agent_data,
            agent_error=agent_error,
            order_stats=order_stats,
            order_stats_error=order_stats_error,
            catalog_stats=catalog_stats,
            catalog_stats_error=catalog_stats_error,
        )


# Earliest year available in the legacy CDR database
_REPORT_MIN_YEAR = 2020


class MonthlyCarrierReportView(BaseView):
    """Flask-Admin view for interactive monthly 3-carrier CDR reports.

    Displays per-day minute totals for Fonotarot, Alotarot and Latam carriers
    for any selected month/year, backed by the legacy portal database.
    """

    def is_accessible(self):
        return current_user and current_user.is_authenticated and current_user.has_role("admin")

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for("security.login", next=request.url))

    @expose("/", methods=["GET"])
    def index(self):
        today = date.today()
        try:
            year = int(request.args.get("year", today.year))
            month = int(request.args.get("month", today.month))
        except (ValueError, TypeError):
            year, month = today.year, today.month

        month = max(1, min(12, month))
        year = max(_REPORT_MIN_YEAR, min(today.year + 1, year))

        data = None
        error = None
        try:
            from .legacy.views import _fetch_monthly_3carrier

            data = _fetch_monthly_3carrier(year, month)
        except Exception as exc:
            error = str(exc)

        return self.render(
            "admin/legacy/monthly_report.html",
            year=year,
            month=month,
            months_es=_MONTHS_ES,
            min_year=_REPORT_MIN_YEAR,
            data=data,
            error=error,
            today=today,
        )


class MonthlyStoreReportView(BaseView):
    """Flask-Admin view for interactive monthly store/sales reports.

    Displays sales by provider, minute packs, gift cards and discount codes
    for any selected month/year.
    """

    def is_accessible(self):
        return current_user and current_user.is_authenticated and current_user.has_role("admin")

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for("security.login", next=request.url))

    @expose("/", methods=["GET"])
    def index(self):
        today = date.today()
        try:
            year = int(request.args.get("year", today.year))
            month = int(request.args.get("month", today.month))
        except (ValueError, TypeError):
            year, month = today.year, today.month

        month = max(1, min(12, month))
        year = max(_REPORT_MIN_YEAR, min(today.year + 1, year))

        catalog_stats = None
        catalog_stats_error = None
        try:
            catalog_stats = self.admin.index_view._fetch_catalog_stats(year, month)
        except Exception as exc:
            catalog_stats_error = str(exc)

        try:
            from .utils import _fetch_order_stats

            order_stats = _fetch_order_stats(year=year, month=month)
        except Exception as exc:
            order_stats_error = str(exc)

        # Calculate month timestamps for the chart
        import datetime

        month_start_dt = datetime.datetime(year, month, 1)
        if month == 12:
            month_end_dt = datetime.datetime(year + 1, 1, 1)
        else:
            month_end_dt = datetime.datetime(year, month + 1, 1)

        start_ms = int(month_start_dt.timestamp() * 1000)
        end_ms = int(month_end_dt.timestamp() * 1000)

        return self.render(
            "admin/monthly_store_report.html",
            year=year,
            month=month,
            months_es=_MONTHS_ES,
            min_year=_REPORT_MIN_YEAR,
            catalog_stats=catalog_stats,
            catalog_stats_error=catalog_stats_error,
            order_stats=order_stats if "order_stats" in locals() else None,
            order_stats_error=order_stats_error if "order_stats_error" in locals() else None,
            start_ms=start_ms,
            end_ms=end_ms,
            today=today,
        )


class MonthlyAgentReportView(BaseView):
    """Flask-Admin view for interactive monthly per-agent CDR reports.

    Displays per-day minute totals for all agents (or a filtered subset)
    for any selected month/year.  Agents are identified by their 7XXX extension.
    """

    def is_accessible(self):
        return current_user and current_user.is_authenticated and current_user.has_role("admin")

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for("security.login", next=request.url))

    @expose("/", methods=["GET"])
    def index(self):
        from .legacy.views import AGENT_REGISTRY, _fetch_all_agents_monthly_cdr

        today = date.today()
        try:
            year = int(request.args.get("year", today.year))
            month = int(request.args.get("month", today.month))
        except (ValueError, TypeError):
            year, month = today.year, today.month

        month = max(1, min(12, month))
        year = max(_REPORT_MIN_YEAR, min(today.year + 1, year))

        # Agent filter: list of 7XXX extensions from checkboxes; empty = all agents.
        selected_raw = request.args.getlist("agents")
        try:
            agent_ids = tuple(int(x) for x in selected_raw if x) or None
        except ValueError:
            agent_ids = None

        data = None
        error = None
        try:
            data = _fetch_all_agents_monthly_cdr(year, month, agent_ids)
        except Exception as exc:
            error = str(exc)

        return self.render(
            "admin/legacy/agent_monthly_report.html",
            year=year,
            month=month,
            months_es=_MONTHS_ES,
            min_year=_REPORT_MIN_YEAR,
            data=data,
            error=error,
            today=today,
            all_agents=sorted(AGENT_REGISTRY.items()),
            selected_agents=set(agent_ids) if agent_ids else set(),
        )


class SecureModelView(ModelView):
    """ModelView accessible only to authenticated users with the 'admin' role."""

    column_type_formatters = dict(ModelView.column_type_formatters)

    can_view_details = True

    def is_accessible(self):
        return current_user and current_user.is_authenticated and current_user.has_role("admin")

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for("security.login", next=request.url))


class SecureFileAdmin(FileAdmin):
    """FileAdmin accessible only to authenticated users with the 'admin' role."""

    def is_accessible(self):
        return current_user and current_user.is_authenticated and current_user.has_role("admin")

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for("security.login", next=request.url))


_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "svg", "avif"}


class MediaLibraryAdmin(SecureFileAdmin):
    """FileAdmin for the media-library folder — images only."""

    allowed_extensions = _IMAGE_EXTENSIONS
    list_template = "admin/media/list.html"

    def is_file_allowed(self, filename):
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        return ext in _IMAGE_EXTENSIONS


_THUMB_SIZE = (240, 240)


class MediaBrowserView(BaseView):
    """Hidden JSON API that returns images from the media-library folder.

    Endpoints
    ---------
    GET /media/          — JSON list of {name, url, thumb_url} for every image.
    GET /media/thumb     — Returns a 240×240 thumbnail for ?f=<filename>,
                           generated on first request and cached in .thumbs/.
    """

    def is_accessible(self):
        return current_user and current_user.is_authenticated and current_user.has_role("admin")

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for("security.login", next=request.url))

    def is_visible(self):
        return False

    @staticmethod
    def _media_path() -> str:
        return os.path.join(os.path.dirname(__file__), "static", "media-library")

    @expose("/")
    def images(self):
        media_path = self._media_path()
        files = []
        if os.path.isdir(media_path):
            for name in sorted(os.listdir(media_path)):
                if name.startswith("."):
                    continue
                ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                if ext in _IMAGE_EXTENSIONS:
                    files.append(
                        {
                            "name": name,
                            "url": url_for("static", filename=f"media-library/{name}"),
                            "thumb_url": url_for("media_browser.thumb", f=name),
                        }
                    )
        return jsonify(files)

    @expose("/thumb")
    def thumb(self):
        """Return a 240×240 thumbnail for the requested media-library image.

        The thumbnail is generated once and cached in media-library/.thumbs/.
        Path traversal is rejected — only bare filenames with known image
        extensions are accepted.
        """
        from flask import abort, send_file
        from PIL import Image

        filename = request.args.get("f", "")
        # Reject anything that looks like a path traversal.
        if not filename or os.sep in filename or "/" in filename or ".." in filename:
            abort(400)
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in _IMAGE_EXTENSIONS:
            abort(400)

        media_path = self._media_path()
        src = os.path.join(media_path, filename)
        if not os.path.isfile(src):
            abort(404)

        thumbs_dir = os.path.join(media_path, ".thumbs")
        os.makedirs(thumbs_dir, exist_ok=True)
        thumb_path = os.path.join(thumbs_dir, filename)

        if not os.path.isfile(thumb_path):
            with Image.open(src) as img:
                img = img.convert("RGB") if img.mode not in ("RGB", "RGBA") else img
                img.thumbnail(_THUMB_SIZE, Image.LANCZOS)
                save_fmt = "JPEG" if ext in ("jpg", "jpeg") else ext.upper()
                img.save(thumb_path, format=save_fmt, quality=82, optimize=True)

        mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
        return send_file(thumb_path, mimetype=mime, max_age=86400)


class UserAdminView(SecureModelView):
    """Admin view for the User model."""

    column_list = ("email", "username", "active", "roles", "firenze_client_id", "created_at")
    column_searchable_list = ("email", "username")
    column_filters = ("firenze_client_id", "email", "username")
    form_excluded_columns = ("password", "fs_uniquifier", "created_at")
    column_relationship_links = True

    @action(
        "reprocess_registration",
        _l("Reprocesar registro"),
        _l("Ejecuta nuevamente el flujo posterior al registro para los usuarios seleccionados."),
    )
    def action_reprocess_registration(self, ids):
        """Rerun the standard post-registration flow for selected users."""
        from flask import flash

        from .actions import process_user_registration

        processed = 0
        missing = 0
        for user_id in ids:
            user = self.session.get(self.model, int(user_id))
            if user is None:
                missing += 1
                continue

            process_user_registration(user)
            processed += 1

        if processed:
            flash(
                _l("%(count)s usuario(s) reprocesado(s).") % {"count": processed},
                "success",
            )
        if missing:
            flash(
                _l("%(count)s usuario(s) no se encontraron.") % {"count": missing},
                "warning",
            )

    @action(
        "fix_totp",
        _l("Generar Secretos TOTP"),
        _l("Regenera secreto TOTP para el usuario."),
    )
    def action_fix_totp(self, ids):
        """Rerun the standard post-registration flow for selected users."""
        from flask import flash

        from .auth_handlers import ensure_user_email_signin

        processed = 0
        missing = 0
        for user_id in ids:
            user = self.session.get(self.model, int(user_id))
            if user is None:
                missing += 1
                continue

            ensure_user_email_signin(user)
            processed += 1

        if processed:
            flash(
                _l("%(count)s usuario(s) reprocesado(s).") % {"count": processed},
                "success",
            )
        if missing:
            flash(
                _l("%(count)s usuario(s) no se encontraron.") % {"count": missing},
                "warning",
            )


class RoleAdminView(SecureModelView):
    """Admin view for the Role model."""

    column_list = (
        "name",
        "description",
    )
    column_searchable_list = ("name",)
    column_relationship_links = True


class StaticPageAdminView(SecureModelView):
    """Admin view for the StaticPage model.

    Uses a GrapesJS visual editor for the HTML content field.
    The path is automatically normalised (slugified) on save.
    """

    column_list = ("path", "title", "is_active", "created_at", "updated_at")
    column_searchable_list = ("path", "title")
    column_filters = ("is_active", "path", "title")
    form_excluded_columns = ("created_at", "updated_at")
    form_widget_args = {
        "featured_image_url": {
            "placeholder": "https://ejemplo.com/imagen.jpg",
        },
    }
    column_descriptions = {
        "featured_image_url": "URL absoluta de la imagen destacada (1200×630 recomendado).",
    }
    edit_template = "admin/staticpage/edit.html"
    create_template = "admin/staticpage/create.html"

    def on_model_change(self, form, model, is_created):
        from .models import StaticPage

        model.path = StaticPage.normalize_path(model.path)
        if model.is_homepage:
            # Ensure only one page is the homepage at a time.
            self.session.query(StaticPage).filter(StaticPage.id != model.id).update(
                {"is_homepage": False}, synchronize_session="fetch"
            )


class BlogPostAdminView(SecureModelView):
    """Admin view for the BlogPost model.

    Uses HugeRTE for visual HTML editing.
    The slug is automatically generated from the title when not provided.
    """

    column_list = ("slug", "title", "published", "published_at", "created_at")
    column_searchable_list = ("slug", "title")
    column_filters = ("published",)
    form_excluded_columns = ("created_at", "updated_at")
    form_widget_args = {
        "featured_image_url": {
            "placeholder": "https://ejemplo.com/imagen.jpg",
        },
    }
    column_descriptions = {
        "featured_image_url": "URL absoluta de la imagen destacada (1200×630 recomendado).",
    }
    create_template = "admin/blog/create.html"
    edit_template = "admin/blog/edit.html"
    details_template = "admin/blog/details.html"

    def on_model_change(self, form, model, is_created):
        from .models import BlogPost

        if not model.slug and model.title:
            model.slug = BlogPost.make_slug(model.title)
        elif model.slug:
            model.slug = BlogPost.make_slug(model.slug)
        if model.published and model.published_at is None:
            from datetime import datetime

            model.published_at = datetime.now()


class MinutePackAdminView(SecureModelView):
    """Admin view for prepaid tarot minute packs."""

    column_list = ("minutes", "price", "is_featured", "is_active", "created_at")
    column_searchable_list = ("description",)
    column_filters = ("is_active", "is_featured")
    form_excluded_columns = ("created_at",)
    column_relationship_links = True


class SubscriptionPlanAdminView(SecureModelView):
    """Admin view for subscription plans."""

    column_list = ("name", "minutes_per_month", "price", "is_featured", "is_active")
    column_searchable_list = ("name",)
    column_filters = ("is_active", "is_featured")
    form_excluded_columns = ("created_at",)


class ProductCategoryAdminView(SecureModelView):
    """Admin view for product categories."""

    column_list = ("slug", "name")
    column_searchable_list = ("slug", "name")
    form_excluded_columns = ()


class ProductAdminView(SecureModelView):
    """Admin view for physical products."""

    column_list = ("name", "category", "price", "stock", "is_active", "is_featured")
    column_searchable_list = ("name", "slug")
    column_filters = ("is_active", "is_featured", "category.name")
    form_excluded_columns = ("created_at", "updated_at", "images")
    create_template = "admin/product/create.html"
    edit_template = "admin/product/create.html"
    column_relationship_links = True

    def on_model_change(self, form, model, is_created):
        from .models import Product

        gallery_raw = request.form.get("gallery_images", "").strip()
        gallery_urls: list[str] = []
        if gallery_raw:
            try:
                parsed = json.loads(gallery_raw)
            except json.JSONDecodeError:
                parsed = []
            if isinstance(parsed, list):
                gallery_urls = [u.strip() for u in parsed if isinstance(u, str) and u.strip()]
                gallery_urls = list(dict.fromkeys(gallery_urls))

        if model.image_url:
            featured = model.image_url.strip()
            if featured and featured not in gallery_urls:
                gallery_urls.insert(0, featured)
        elif gallery_urls:
            model.image_url = gallery_urls[0]

        model.images = gallery_urls or None

        if not model.slug and model.name:
            model.slug = Product.make_slug(model.name)
        elif model.slug:
            model.slug = Product.make_slug(model.slug)


class GiftCardProductAdminView(SecureModelView):
    """Admin view for digital prepaid gift-card products."""

    column_list = ("name", "minutes", "price", "is_active", "is_featured", "updated_at")
    column_searchable_list = ("name", "slug")
    column_filters = ("is_active", "is_featured")
    form_excluded_columns = ("created_at", "updated_at")
    form_widget_args = {
        "image_url": {
            "placeholder": "https://ejemplo.com/tarjeta.jpg",
        },
    }
    column_descriptions = {
        "image_url": "URL de imagen principal para la tarjeta digital.",
    }
    create_template = "admin/giftcard_product/create.html"
    edit_template = "admin/giftcard_product/create.html"
    column_relationship_links = True

    def on_model_change(self, form, model, is_created):
        from .models import GiftCardProduct

        if not model.slug and model.name:
            model.slug = GiftCardProduct.make_slug(model.name)
        elif model.slug:
            model.slug = GiftCardProduct.make_slug(model.slug)


class GiftCardAdminView(SecureModelView):
    """Admin view for issued/redeemed gift-card codes."""

    can_create = True
    can_delete = False
    can_edit = False
    column_list = (
        "code",
        "gift_card_product",
        "order_id",
        "status",
        "purchaser_email",
        "recipient_email",
        "redeemed_at",
        "created_at",
    )
    column_relationship_links = True
    column_searchable_list = ("code", "purchaser_email", "recipient_email")
    column_filters = ("status", "gift_card_product.name", "created_at", "redeemed_at")
    column_descriptions = {
        "order_id": "Opcional. Déjalo vacío para tarjetas creadas manualmente desde admin.",
    }

    def create_form(self, obj=None):
        form = super().create_form(obj)
        if not form.code.data:
            from .tienda.tarjetas.service import generate_unique_gift_code

            form.code.data = generate_unique_gift_code()
        return form


class SiteSettingsAdminView(SecureModelView):
    """Admin view for generic site settings."""

    json_columns = ["value"]
    column_list = ("key", "value", "module", "description")
    column_searchable_list = ("key", "module")
    column_filters = ("module",)
    column_editable_list = ("value",)


_ANALYTICS_KEYS = [
    (
        "umami_website_id",
        "Umami",
        "Website ID",
        "El ID del sitio en el dashboard de Umami.",
    ),
    (
        "umami_email_pixel_id",
        "Umami",
        "Email Pixel ID",
        "Token que aparece después de /p/ en la URL del pixel.",
    ),
    (
        "gtm_container_id",
        "Google",
        "GTM Container",
        "ID del contenedor GTM, ej. GTM-XXXXXXX.",
    ),
    (
        "ga_measurement_id",
        "Google",
        "GA4 Measurement ID",
        "ID de medición GA4, ej. G-XXXXXXXXXX.",
    ),
    ("meta_pixel_id", "Meta", "Pixel ID", "ID del Meta (Facebook) Pixel."),
    (
        "segment_write_key",
        "Segment",
        "Write Key",
        "Clave de escritura de la fuente en Twilio Segment.",
    ),
]


def _save_setting(key: str, value: str, module: str) -> None:
    """Save *value* for *key*, or delete the row when *value* is empty."""
    from .extensions import db
    from .models import SiteSettings

    if value:
        SiteSettings.set(key, value, module=module)
    else:
        row = SiteSettings.query.filter_by(key=key).first()
        if row is not None:
            db.session.delete(row)
            db.session.commit()


class AnalyticsSettingsAdminView(BaseView):
    """Settings page that always shows all analytics tracker keys.

    Reads current values from SiteSettings and saves changes via
    SiteSettings.set(), creating rows that do not yet exist.
    """

    def is_accessible(self):
        return current_user and current_user.is_authenticated and current_user.has_role("admin")

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for("security.login", next=request.url))

    @expose("/", methods=["GET", "POST"])
    def index(self):
        from .models import SiteSettings

        if request.method == "POST":
            for key, *_ in _ANALYTICS_KEYS:
                value = request.form.get(key, "").strip()
                _save_setting(key, value, module="analytics")

        values = {key: (SiteSettings.get(key) or "") for key, *_ in _ANALYTICS_KEYS}
        return self.render(
            "admin/analytics_settings.html",
            keys=_ANALYTICS_KEYS,
            values=values,
        )


_SEO_KEYS = [
    # (key, section, label, hint, template_default)
    (
        "seo_site_title",
        "Sitio",
        "Título del sitio",
        "Título por defecto en la pestaña del navegador y resultados de búsqueda.",
        "Fonotarot - Tarot por Teléfono con Personas Reales | Chile",
    ),
    (
        "seo_site_description",
        "Sitio",
        "Descripción",
        "Meta descripción por defecto (aprox. 155 caracteres).",
        (
            "Consulta con tarotistas reales por teléfono en Chile. Planes desde 15 min. "
            "Disponible 24/7. Amor, trabajo, salud y más."
        ),
    ),
    (
        "seo_site_keywords",
        "Sitio",
        "Keywords",
        "Palabras clave separadas por coma (uso moderno limitado).",
        "tarot telefónico, tarot por teléfono, tarot Chile, tarotistas Chile, consulta tarot",
    ),
    ("seo_site_author", "Sitio", "Autor", "Valor del meta tag author.", "Fonotarot"),
    (
        "seo_copyright",
        "Sitio",
        "Copyright",
        "Texto de copyright para el meta tag.",
        "Fonotarot",
    ),
    (
        "seo_robots",
        "Sitio",
        "Robots",
        "Directiva para todos los bots, ej. 'index, follow' o 'noindex, nofollow'.",
        "index, follow, max-snippet:-1, max-image-preview:large, max-video-preview:-1",
    ),
    (
        "seo_language",
        "Sitio",
        "Idioma",
        "Valor del meta tag language, ej. 'Spanish'.",
        "Spanish",
    ),
    (
        "seo_geo_region",
        "Geo",
        "Región",
        "Código ISO de región, ej. 'CL', 'MX-CMX'.",
        "CL",
    ),
    ("seo_geo_country", "Geo", "País", "Nombre del país, ej. 'Chile'.", "Chile"),
    (
        "seo_geo_placename",
        "Geo",
        "Lugar",
        "Ciudad o lugar principal, ej. 'Santiago'.",
        "Chile",
    ),
    (
        "seo_og_site_name",
        "Open Graph",
        "Nombre del sitio",
        "og:site_name — nombre del sitio en compartidos de redes sociales.",
        "Fonotarot",
    ),
    (
        "seo_og_image_url",
        "Open Graph",
        "Imagen OG",
        "URL absoluta de la imagen por defecto para og:image y twitter:image.",
        "/static/og-image.png",
    ),
    (
        "seo_twitter_card",
        "Twitter / X",
        "Card type",
        "Tipo de card: 'summary_large_image' (imagen grande) o 'summary' (miniatura).",
        "summary_large_image",
    ),
    (
        "seo_twitter_handle",
        "Twitter / X",
        "Handle",
        "Cuenta de Twitter/X sin @, ej. fonotarot. Usada en twitter:site y twitter:creator.",
        "fonotarot",
    ),
    (
        "seo_app_title",
        "Mobile / PWA",
        "Nombre de la app",
        "apple-mobile-web-app-title — nombre corto que aparece bajo el ícono en iOS.",
        "Fonotarot",
    ),
    (
        "seo_theme_color_light",
        "Mobile / PWA",
        "Theme color (claro)",
        "Color de la barra del navegador en modo claro.",
        "#faf7f3",
    ),
    (
        "seo_theme_color_dark",
        "Mobile / PWA",
        "Theme color (oscuro)",
        "Color de la barra del navegador en modo oscuro.",
        "#1a1a2e",
    ),
    (
        "seo_tile_color",
        "Mobile / PWA",
        "Tile color",
        "Color del tile de Windows (msapplication-TileColor y navbutton-color).",
        "#6b3fa0",
    ),
    (
        "seo_google_verification",
        "Webmaster",
        "Google Verification",
        "Contenido del meta tag google-site-verification (Google Search Console).",
        "",
    ),
    (
        "seo_bing_verification",
        "Webmaster",
        "Bing Verification",
        "Contenido del meta tag msvalidate.01 (Bing Webmaster Tools).",
        "",
    ),
]


class SeoSettingsAdminView(BaseView):
    """Settings page for site-wide SEO meta tags (module='seo').

    Always renders all keys, pre-filled from SiteSettings.
    base.html reads these values and falls back to its hardcoded defaults
    when a key is absent or empty.
    """

    def is_accessible(self):
        return current_user and current_user.is_authenticated and current_user.has_role("admin")

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for("security.login", next=request.url))

    @expose("/", methods=["GET", "POST"])
    def index(self):
        from .models import SiteSettings

        _COLOR_KEYS = (
            "seo_theme_color_light",
            "seo_theme_color_dark",
            "seo_tile_color",
        )
        if request.method == "POST":
            for key, *_ in _SEO_KEYS:
                # Color fields post a paired _text input; prefer it so the
                # user can clear the value by emptying the text box.
                if key in _COLOR_KEYS:
                    value = request.form.get(f"{key}_text", "").strip()
                else:
                    value = request.form.get(key, "").strip()
                _save_setting(key, value, module="seo")

        values = {key: (SiteSettings.get(key) or "") for key, *_ in _SEO_KEYS}
        return self.render(
            "admin/seo_settings.html",
            keys=_SEO_KEYS,
            values=values,
        )


class DiscountCodeAdminView(SecureModelView):
    """Admin view for DiscountCode."""

    can_create = True
    can_edit = True
    can_delete = True
    can_view_details = True
    column_searchable_list = ["code"]
    column_filters = ["code", "discount_type", "is_active", "valid_from", "valid_to"]
    column_list = [
        "code",
        "discount_type",
        "discount_value",
        "currency",
        "is_active",
        "uses_count",
        "max_uses",
    ]
    form_columns = [
        "code",
        "discount_type",
        "discount_value",
        "currency",
        "is_active",
        "valid_from",
        "valid_to",
        "max_uses",
    ]
    column_relationship_links = True


class ModelLinkRowAction(EndpointLinkRowAction):
    """
    Like EndpointLinkRowAction, but each value in url_args is treated as
    an attribute name on `row` and resolved at render time — instead of
    being passed straight through to url_for(), and instead of always
    appending the row's PK as `id_arg`.

    Usage:
        ModelLinkRowAction("ti ti-graph", "pagos.orden_estado",
                            url_args={"order_id": "merchants_id"})

    -> url_for("pagos.orden_estado", order_id=row.merchants_id)
    """

    def render(self, context, row_id, row):
        m = self._resolve_symbol(context, "row_actions.link")
        get_url = self._resolve_symbol(context, "get_url")

        kwargs = {key: getattr(row, attr_name) for key, attr_name in (self.url_args or {}).items()}

        url = get_url(self.endpoint, **kwargs)
        return m(self, url)


class OrderAdminView(SecureModelView):
    """Admin view for customer orders."""

    details_template = "admin/order/details.html"
    json_columns = [
        "extra_args",
        "request_payload",
        "response_payload",
        "payment_object",
        "firenze_payload",
        "firenze_response",
    ]
    column_list = (
        "status",
        "discount_code",
        "amount",
        "provider",
        "email",
        "shipping_phone",
        "firenze_client_id",
        "created_at",
    )
    column_filters = ("status", "provider", "firenze_client_id", "email", "status", "transaction_id", "merchants_id")
    can_create = False
    form_excluded_columns = ("created_at", "updated_at", "items")
    column_sortable_list = ("firenze_client_id", "created_at", "provider")
    column_searchable_list = ("firenze_client_id", "email", "shipping_phone", "transaction_id", "merchants_id")
    page_size = 50
    column_relationship_links = True
    column_default_sort = ("created_at", True)
    column_extra_row_actions = [
        ModelLinkRowAction("ti ti-graph", "pagos.orden_estado", url_args={"order_id": "merchants_id"})
    ]

    @action("post_purchase", "Proceso post webhook")
    def action_post_purchase(self, ids):
        """This ejecutes the process after a webhook, no modifications"""
        from .signals import post_purchase_process

        for order_id in ids:
            post_purchase_process(order_id=order_id)

    @action(
        "completar_orden",
        "Completar Orden",
        "¿Completar las órdenes seleccionadas? Solo se procesarán las que tengan estado de pago 'succeeded'.",
    )
    def action_completar_orden(self, ids):
        """Complete selected orders: call Firenze, then complete when sync succeeds.

        Only orders whose payment ``payment_status`` is ``succeeded`` are processed.
        If Firenze sync fails, the order remains PENDING and admins are
        notified so the operator can follow up.
        """
        from flask import flash

        from .extensions import db
        from .models import Order
        from .tienda.pagos.views import _complete_succeeded_order_admin_flow

        processed = 0
        pending_firenze = 0
        skipped = 0
        for order_id in ids:
            order = db.session.get(Order, int(order_id))
            if order is None:
                continue
            if order.payment_status != "succeeded":
                skipped += 1
                continue

            if _complete_succeeded_order_admin_flow(order, "admin-action"):
                processed += 1
            else:
                pending_firenze += 1

        if processed:
            flash(
                f"{processed} orden(es) completada(s) y marcada(s) como pagadas.",
                "success",
            )
        if pending_firenze:
            flash(
                f"{pending_firenze} orden(es) siguen PENDING porque Firenze falló; se notificó a admins.",
                "warning",
            )
        if skipped:
            flash(
                f"{skipped} orden(es) omitida(s): el pago no está en estado 'succeeded'.",
                "warning",
            )


def init_admin(app, admin_ext):
    """Register model views on the Admin instance."""
    from .models import (
        BlogPost,
        GiftCard,
        GiftCardProduct,
        MinutePack,
        Order,
        Product,
        ProductCategory,
        Role,
        SiteSettings,
        StaticPage,
        SubscriptionPlan,
        User,
    )

    admin_ext.add_category(
        name=_l("Inicio"),
        icon_type="ti",
        icon_value="home-2",
    )
    admin_ext.add_category(
        name=_l("Auth"),
        icon_type="ti",
        icon_value="lock",
    )
    admin_ext.add_category(
        name=_l("Content"),
        icon_type="ti",
        icon_value="layout-dashboard",
    )
    admin_ext.add_category(
        name=_l("Tienda"),
        icon_type="ti",
        icon_value="building-store",
    )
    admin_ext.add_category(
        name=_l("Sitio"),
        icon_type="ti",
        icon_value="globe",
    )
    admin_ext.add_category(
        name=_l("Reportes"),
        icon_type="ti",
        icon_value="report",
    )
    admin_ext.add_category(
        name=_l("Merchants"),
        icon_type="ti",
        icon_value="credit-card-pay",
    )
    admin_ext.add_view(
        UserAdminView(
            User,
            db.session,
            name=_l("Users"),
            category=_l("Auth"),
            menu_icon_type="ti",
            menu_icon_value="users",
        )
    )
    admin_ext.add_view(
        RoleAdminView(
            Role,
            db.session,
            name=_l("Roles"),
            category=_l("Auth"),
            menu_icon_type="ti",
            menu_icon_value="shield",
        )
    )
    admin_ext.add_view(
        StaticPageAdminView(
            StaticPage,
            db.session,
            name=_l("Pages"),
            category=_l("Content"),
            menu_icon_type="ti",
            menu_icon_value="file-text",
        )
    )
    admin_ext.add_view(
        BlogPostAdminView(
            BlogPost,
            db.session,
            name=_l("Blog Posts"),
            category=_l("Content"),
            menu_icon_type="ti",
            menu_icon_value="file-text",
        )
    )
    admin_ext.add_view(
        MinutePackAdminView(
            MinutePack,
            db.session,
            name=_l("Packs de Minutos"),
            category=_l("Tienda"),
            menu_icon_type="ti",
            menu_icon_value="clock",
        )
    )
    from .models import DiscountCode

    admin_ext.add_view(
        DiscountCodeAdminView(
            DiscountCode,
            db.session,
            name=_l("Códigos de Descuento"),
            category=_l("Tienda"),
            menu_icon_type="ti",
            menu_icon_value="discount-2",
        )
    )
    admin_ext.add_view(
        SubscriptionPlanAdminView(
            SubscriptionPlan,
            db.session,
            name=_l("Suscripciones"),
            category=_l("Tienda"),
            menu_icon_type="ti",
            menu_icon_value="credit-card",
        )
    )
    admin_ext.add_view(
        ProductCategoryAdminView(
            ProductCategory,
            db.session,
            name=_l("Categorías"),
            category=_l("Tienda"),
            menu_icon_type="ti",
            menu_icon_value="tag",
        )
    )
    admin_ext.add_view(
        ProductAdminView(
            Product,
            db.session,
            name=_l("Productos"),
            category=_l("Tienda"),
            menu_icon_type="ti",
            menu_icon_value="package",
        )
    )
    admin_ext.add_view(
        GiftCardProductAdminView(
            GiftCardProduct,
            db.session,
            name=_l("Tarjetas Digitales"),
            category=_l("Tienda"),
            menu_icon_type="ti",
            menu_icon_value="ticket",
        )
    )
    admin_ext.add_view(
        GiftCardAdminView(
            GiftCard,
            db.session,
            name=_l("Códigos de Tarjetas"),
            category=_l("Tienda"),
            menu_icon_type="ti",
            menu_icon_value="ticket-off",
        )
    )
    admin_ext.add_view(
        OrderAdminView(
            Order,
            db.session,
            name=_l("Órdenes"),
            category=_l("Tienda"),
            menu_icon_type="ti",
            menu_icon_value="shopping-cart",
        )
    )
    admin_ext.add_view(
        SiteSettingsAdminView(
            SiteSettings,
            db.session,
            name=_l("Configuración"),
            category=_l("Sitio"),
            menu_icon_type="ti",
            menu_icon_value="settings",
        )
    )
    admin_ext.add_view(
        SeoSettingsAdminView(
            name=_l("SEO"),
            endpoint="seo_settings",
            category=_l("Sitio"),
            menu_icon_type="ti",
            menu_icon_value="search",
        )
    )
    admin_ext.add_view(
        AnalyticsSettingsAdminView(
            name=_l("Analytics"),
            endpoint="analytics_settings",
            category=_l("Sitio"),
            menu_icon_type="ti",
            menu_icon_value="chart-dots",
        )
    )
    admin_ext.add_view(
        MonthlyStoreReportView(
            name=_l("Reporte Tienda"),
            endpoint="monthly_store_report",
            category=_l("Reportes"),
            menu_icon_type="ti",
            menu_icon_value="shopping-cart",
        )
    )
    admin_ext.add_view(
        MonthlyCarrierReportView(
            name=_l("Reporte Mensual"),
            endpoint="monthly_report",
            category=_l("Reportes"),
            menu_icon_type="ti",
            menu_icon_value="chart-bar",
        )
    )
    admin_ext.add_view(
        MonthlyAgentReportView(
            name=_l("Reporte Agentes"),
            endpoint="monthly_agent_report",
            category=_l("Reportes"),
            menu_icon_type="ti",
            menu_icon_value="users",
        )
    )
    static_path = os.path.join(os.path.dirname(__file__), "static")
    media_path = os.path.join(static_path, "media-library")
    admin_ext.add_view(
        MediaLibraryAdmin(
            media_path,
            "/static/media-library/",
            name=_l("Media Library"),
            category=_l("Content"),
            endpoint="media_library",
            menu_icon_type="ti",
            menu_icon_value="photo",
        )
    )
    admin_ext.add_view(
        SecureFileAdmin(
            static_path,
            "/static/",
            name=_l("Static Files"),
            category=_l("Content"),
            endpoint="static_files",
            menu_icon_type="ti",
            menu_icon_value="folder",
        )
    )
    admin_ext.add_view(
        MediaBrowserView(
            name="media_browser",
            endpoint="media_browser",
            url="/media",
        )
    )
    admin_ext.add_link(MenuLink(name=_l("Sitio Web"), url="/", icon_type="ti", icon_value="home"))
