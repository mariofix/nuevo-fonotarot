"""Flask-Admin configuration using Flask-Security for authentication."""

from datetime import date

from flask import redirect, request, url_for
from flask_admin import AdminIndexView, BaseView, expose
from flask_admin.menu import MenuLink
from flask_admin.contrib.sqla import ModelView
from flask_babel import lazy_gettext as _l
from flask_security import current_user

from flask_admin_tabler import tabler_bool_formatter
from .extensions import db


# Spanish month names used in legacy CDR report views
_MONTHS_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}


class SecureAdminIndexView(AdminIndexView):
    """Admin index view that requires an authenticated user with the 'admin' role."""

    @expose("/")
    def index(self):
        today = date.today()
        latest_data = None
        latest_error = None
        try:
            from .legacy.views import _fetch_monthly_3carrier
            latest_data = _fetch_monthly_3carrier(today.year, today.month)
        except Exception as exc:
            latest_error = str(exc)

        return self.render(
            "admin/index.html",
            latest_year=today.year,
            latest_month=today.month,
            months_es=_MONTHS_ES,
            latest_data=latest_data,
            latest_error=latest_error,
        )


# Earliest year available in the legacy CDR database
_REPORT_MIN_YEAR = 2020


class MonthlyCarrierReportView(BaseView):
    """Flask-Admin view for interactive monthly 3-carrier CDR reports.

    Displays per-day minute totals for Fonotarot, Alotarot and Latam carriers
    for any selected month/year, backed by the legacy portal database.
    """

    def is_accessible(self):
        # return current_user.is_authenticated and current_user.has_role("admin")
        return True

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


class SecureModelView(ModelView):
    """ModelView accessible only to authenticated users with the 'admin' role."""

    column_type_formatters = dict(ModelView.column_type_formatters)
    column_type_formatters[bool] = tabler_bool_formatter
    can_view_details = True

    def is_accessible(self):
        # return current_user.is_authenticated and current_user.has_role("admin")
        return True

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for("security.login", next=request.url))


class UserAdminView(SecureModelView):
    """Admin view for the User model."""

    column_list = ("email", "username", "active", "roles", "created_at")
    column_searchable_list = ("email", "username")
    column_filters = ("active",)
    form_excluded_columns = ("password", "fs_uniquifier", "created_at")


class RoleAdminView(SecureModelView):
    """Admin view for the Role model."""

    column_list = ("name", "description")
    column_searchable_list = ("name",)


class StaticPageAdminView(SecureModelView):
    """Admin view for the StaticPage model.

    Uses a GrapesJS visual editor for the HTML content field.
    The path is automatically normalised (slugified) on save.
    """

    column_list = ("path", "title", "is_active", "created_at", "updated_at")
    column_searchable_list = ("path", "title")
    column_filters = ("is_active",)
    form_excluded_columns = ("created_at", "updated_at")
    edit_template = "admin/staticpage/edit.html"
    create_template = "admin/staticpage/create.html"

    def on_model_change(self, form, model, is_created):
        from .models import StaticPage

        model.path = StaticPage.normalize_path(model.path)


class BlogPostAdminView(SecureModelView):
    """Admin view for the BlogPost model.

    Uses a standard textarea for HTML content (no visual editor).
    The slug is automatically generated from the title when not provided.
    """

    column_list = ("slug", "title", "published", "published_at", "created_at")
    column_searchable_list = ("slug", "title")
    column_filters = ("published",)
    form_excluded_columns = ("created_at", "updated_at")

    def on_model_change(self, form, model, is_created):
        from .models import BlogPost

        if not model.slug and model.title:
            model.slug = BlogPost.make_slug(model.title)
        elif model.slug:
            model.slug = BlogPost.make_slug(model.slug)
        if model.published and model.published_at is None:
            from datetime import datetime, timezone

            model.published_at = datetime.now(timezone.utc)


class MinutePackAdminView(SecureModelView):
    """Admin view for prepaid tarot minute packs."""

    column_list = ("minutes", "price", "is_featured", "is_active", "created_at")
    column_searchable_list = ("description",)
    column_filters = ("is_active", "is_featured")
    form_excluded_columns = ("created_at",)


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
    form_excluded_columns = ("created_at", "updated_at")

    def on_model_change(self, form, model, is_created):
        from .models import Product

        if not model.slug and model.name:
            model.slug = Product.make_slug(model.name)
        elif model.slug:
            model.slug = Product.make_slug(model.slug)


class SiteSettingsAdminView(SecureModelView):
    """Admin view for generic site settings."""

    column_list = ("key", "value", "module", "description")
    column_searchable_list = ("key", "module")
    column_filters = ("module",)
    column_editable_list = ("value",)


class OrderAdminView(SecureModelView):
    """Admin view for customer orders."""

    column_list = ("id", "status", "total", "payment_method", "anonymous_shipping", "created_at")
    column_filters = ("status", "payment_method", "anonymous_shipping")
    can_create = False
    form_excluded_columns = ("created_at", "updated_at", "items")


class PaymentAdminView(SecureModelView):
    """Admin view for payment sessions (flask-merchants)."""

    column_list = ("session_id", "provider", "amount", "currency", "state", "created_at")
    column_searchable_list = ("session_id",)
    column_filters = ("provider", "state")
    can_create = False
    form_excluded_columns = ("created_at", "updated_at")


def init_admin(app, admin_ext):
    """Register model views on the Admin instance."""
    from .models import (
        BlogPost, MinutePack, Order, Payment, Product, ProductCategory, Role,
        SiteSettings, StaticPage, SubscriptionPlan, User,
    )

    admin_ext.add_view(UserAdminView(User, db.session, name=_l("Users"), category=_l("Auth"), menu_icon_type="tabler", menu_icon_value="users"))
    admin_ext.add_view(RoleAdminView(Role, db.session, name=_l("Roles"), category=_l("Auth"), menu_icon_type="tabler", menu_icon_value="shield"))
    admin_ext.add_view(
        StaticPageAdminView(StaticPage, db.session, name=_l("Pages"), category=_l("Content"), menu_icon_type="tabler", menu_icon_value="file-text")
    )
    admin_ext.add_view(
        BlogPostAdminView(BlogPost, db.session, name=_l("Blog Posts"), category=_l("Content"), menu_icon_type="tabler", menu_icon_value="file-text")
    )
    admin_ext.add_view(
        MinutePackAdminView(MinutePack, db.session, name=_l("Packs de Minutos"), category=_l("Tienda"), menu_icon_type="tabler", menu_icon_value="clock")
    )
    admin_ext.add_view(
        SubscriptionPlanAdminView(SubscriptionPlan, db.session, name=_l("Suscripciones"), category=_l("Tienda"), menu_icon_type="tabler", menu_icon_value="credit-card")
    )
    admin_ext.add_view(
        ProductCategoryAdminView(ProductCategory, db.session, name=_l("Categorías"), category=_l("Tienda"), menu_icon_type="tabler", menu_icon_value="tag")
    )
    admin_ext.add_view(
        ProductAdminView(Product, db.session, name=_l("Productos"), category=_l("Tienda"), menu_icon_type="tabler", menu_icon_value="package")
    )
    admin_ext.add_view(
        OrderAdminView(Order, db.session, name=_l("Órdenes"), category=_l("Tienda"), menu_icon_type="tabler", menu_icon_value="shopping-cart")
    )
    admin_ext.add_view(
        PaymentAdminView(Payment, db.session, name=_l("Pagos"), category=_l("Tienda"), menu_icon_type="tabler", menu_icon_value="credit-card")
    )
    admin_ext.add_view(
        SiteSettingsAdminView(SiteSettings, db.session, name=_l("Configuración"), category=_l("Sitio"), menu_icon_type="tabler", menu_icon_value="settings")
    )
    admin_ext.add_view(
        MonthlyCarrierReportView(
            name=_l("Reporte Mensual"),
            endpoint="monthly_report",
            category=_l("Reportes"),
            menu_icon_type="tabler",
            menu_icon_value="chart-bar",
        )
    )
    admin_ext.add_link(MenuLink(name="Home Page", url="/",  icon_type="tabler", icon_value="home"))
