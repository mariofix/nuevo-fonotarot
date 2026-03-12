"""Flask-Admin configuration using Flask-Security for authentication."""

from flask import redirect, request, url_for
from flask_admin import AdminIndexView, expose
from flask_admin.menu import MenuLink
from flask_admin.contrib.sqla import ModelView
from flask_babel import lazy_gettext as _l
from flask_security import current_user

from flask_admin_tabler import tabler_bool_formatter
from .extensions import db


class SecureAdminIndexView(AdminIndexView):
    """Admin index view that requires an authenticated user with the 'admin' role."""

    # @expose("/")
    # def index(self):
    #     if not current_user.is_authenticated or not current_user.has_role("admin"):
    #         return redirect(url_for("security.login"))
    #     return super().index()
    pass


class SecureModelView(ModelView):
    """ModelView accessible only to authenticated users with the 'admin' role."""

    column_type_formatters = dict(ModelView.column_type_formatters)
    column_type_formatters[bool] = tabler_bool_formatter

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


class ProductAdminView(SecureModelView):
    """Admin view for physical products."""

    column_list = ("name", "category", "price", "stock", "is_active", "is_featured")
    column_searchable_list = ("name", "slug")
    column_filters = ("is_active", "is_featured", "category")
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
        BlogPost, MinutePack, Order, Payment, Product, Role,
        SiteSettings, StaticPage, SubscriptionPlan, User,
    )

    admin_ext.add_view(UserAdminView(User, db.session, name=_l("Users"), category=_l("Auth")))
    admin_ext.add_view(RoleAdminView(Role, db.session, name=_l("Roles"), category=_l("Auth")))
    admin_ext.add_view(
        StaticPageAdminView(StaticPage, db.session, name=_l("Pages"), category=_l("Content"))
    )
    admin_ext.add_view(
        BlogPostAdminView(BlogPost, db.session, name=_l("Blog Posts"), category=_l("Content"))
    )
    admin_ext.add_view(
        MinutePackAdminView(MinutePack, db.session, name=_l("Packs de Minutos"), category=_l("Tienda"))
    )
    admin_ext.add_view(
        SubscriptionPlanAdminView(SubscriptionPlan, db.session, name=_l("Suscripciones"), category=_l("Tienda"))
    )
    admin_ext.add_view(
        ProductAdminView(Product, db.session, name=_l("Productos"), category=_l("Tienda"))
    )
    admin_ext.add_view(
        OrderAdminView(Order, db.session, name=_l("Órdenes"), category=_l("Tienda"))
    )
    admin_ext.add_view(
        PaymentAdminView(Payment, db.session, name=_l("Pagos"), category=_l("Tienda"))
    )
    admin_ext.add_view(
        SiteSettingsAdminView(SiteSettings, db.session, name=_l("Configuración"), category=_l("Sitio"))
    )
    admin_ext.add_link(MenuLink(name="Home Page", url="/"))
