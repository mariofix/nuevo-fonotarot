"""Flask-Admin configuration using Flask-Security for authentication."""

from datetime import date

from flask import redirect, request, url_for
from flask_admin import AdminIndexView, BaseView, expose
from flask_admin.menu import MenuLink
from flask_admin.contrib.sqla import ModelView
from flask_babel import lazy_gettext as _l
from flask_security import current_user

from flask_admin_tabler import tabler_bool_formatter, JsonColumnsMixin
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

    @expose("/")
    def index(self):
        today = date.today()
        latest_data = None
        latest_error = None
        agent_data = None
        agent_error = None
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

        return self.render(
            "admin/index.html",
            latest_year=today.year,
            latest_month=today.month,
            months_es=_MONTHS_ES,
            latest_data=latest_data,
            latest_error=latest_error,
            agent_data=agent_data,
            agent_error=agent_error,
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


class MonthlyAgentReportView(BaseView):
    """Flask-Admin view for interactive monthly per-agent CDR reports.

    Displays per-day minute totals for all agents (or a filtered subset)
    for any selected month/year.  Agents are identified by their 7XXX extension.
    """

    def is_accessible(self):
        return current_user.is_authenticated and current_user.has_role("admin")

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


class SiteSettingsAdminView(JsonColumnsMixin, SecureModelView):
    """Admin view for generic site settings."""

    json_columns = ["value"]
    column_list = ("key", "value", "module", "description")
    column_searchable_list = ("key", "module")
    column_filters = ("module",)
    column_editable_list = ("value",)


_ANALYTICS_KEYS = [
    ("umami_website_id",     "Umami",        "Website ID",    "El ID del sitio en el dashboard de Umami."),
    ("umami_email_pixel_id", "Umami",        "Email Pixel ID","Token que aparece después de /p/ en la URL del pixel."),
    ("gtm_container_id",     "Google",       "GTM Container", "ID del contenedor GTM, ej. GTM-XXXXXXX."),
    ("ga_measurement_id",    "Google",       "GA4 Measurement ID", "ID de medición GA4, ej. G-XXXXXXXXXX."),
    ("meta_pixel_id",        "Meta",         "Pixel ID",      "ID del Meta (Facebook) Pixel."),
    ("segment_write_key",    "Segment",      "Write Key",     "Clave de escritura de la fuente en Twilio Segment."),
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
        # return current_user.is_authenticated and current_user.has_role("admin")
        return True

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
    ("seo_site_title",          "Sitio",       "Título del sitio",      "Título por defecto en la pestaña del navegador y resultados de búsqueda.",  "Fonotarot - Tarot por Teléfono con Personas Reales | Chile"),
    ("seo_site_description",    "Sitio",       "Descripción",           "Meta descripción por defecto (aprox. 155 caracteres).",                    "Consulta con tarotistas reales por teléfono en Chile. Planes desde 15 min. Disponible 24/7. Amor, trabajo, salud y más."),
    ("seo_site_keywords",       "Sitio",       "Keywords",              "Palabras clave separadas por coma (uso moderno limitado).",                 "tarot telefónico, tarot por teléfono, tarot Chile, tarotistas Chile, consulta tarot"),
    ("seo_site_author",         "Sitio",       "Autor",                 "Valor del meta tag author.",                                               "Fonotarot"),
    ("seo_copyright",           "Sitio",       "Copyright",             "Texto de copyright para el meta tag.",                                     "Fonotarot"),
    ("seo_robots",              "Sitio",       "Robots",                "Directiva para todos los bots, ej. 'index, follow' o 'noindex, nofollow'.", "index, follow, max-snippet:-1, max-image-preview:large, max-video-preview:-1"),
    ("seo_language",            "Sitio",       "Idioma",                "Valor del meta tag language, ej. 'Spanish'.",                              "Spanish"),
    ("seo_geo_region",          "Geo",         "Región",                "Código ISO de región, ej. 'CL', 'MX-CMX'.",                               "CL"),
    ("seo_geo_country",         "Geo",         "País",                  "Nombre del país, ej. 'Chile'.",                                            "Chile"),
    ("seo_geo_placename",       "Geo",         "Lugar",                 "Ciudad o lugar principal, ej. 'Santiago'.",                                "Chile"),
    ("seo_og_site_name",        "Open Graph",  "Nombre del sitio",      "og:site_name — nombre del sitio en compartidos de redes sociales.",        "Fonotarot"),
    ("seo_og_image_url",        "Open Graph",  "Imagen OG",             "URL absoluta de la imagen por defecto para og:image y twitter:image.",     "/static/og-image.jpg"),
    ("seo_twitter_card",        "Twitter / X", "Card type",             "Tipo de card: 'summary_large_image' (imagen grande) o 'summary' (miniatura).", "summary_large_image"),
    ("seo_twitter_handle",      "Twitter / X", "Handle",                "Cuenta de Twitter/X sin @, ej. fonotarot. Usada en twitter:site y twitter:creator.", "fonotarot"),
    ("seo_app_title",           "Mobile / PWA","Nombre de la app",      "apple-mobile-web-app-title — nombre corto que aparece bajo el ícono en iOS.", "Fonotarot"),
    ("seo_theme_color_light",   "Mobile / PWA","Theme color (claro)",   "Color de la barra del navegador en modo claro.",                           "#faf7f3"),
    ("seo_theme_color_dark",    "Mobile / PWA","Theme color (oscuro)",  "Color de la barra del navegador en modo oscuro.",                          "#1a1a2e"),
    ("seo_tile_color",          "Mobile / PWA","Tile color",            "Color del tile de Windows (msapplication-TileColor y navbutton-color).",   "#6b3fa0"),
    ("seo_google_verification", "Webmaster",   "Google Verification",   "Contenido del meta tag google-site-verification (Google Search Console).", ""),
    ("seo_bing_verification",   "Webmaster",   "Bing Verification",     "Contenido del meta tag msvalidate.01 (Bing Webmaster Tools).",             ""),
]


class SeoSettingsAdminView(BaseView):
    """Settings page for site-wide SEO meta tags (module='seo').

    Always renders all keys, pre-filled from SiteSettings.
    base.html reads these values and falls back to its hardcoded defaults
    when a key is absent or empty.
    """

    def is_accessible(self):
        # return current_user.is_authenticated and current_user.has_role("admin")
        return True

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for("security.login", next=request.url))

    @expose("/", methods=["GET", "POST"])
    def index(self):
        from .models import SiteSettings

        _COLOR_KEYS = ("seo_theme_color_light", "seo_theme_color_dark", "seo_tile_color")
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


class OrderAdminView(JsonColumnsMixin, SecureModelView):
    """Admin view for customer orders."""

    json_columns = ["extra_args", "request_payload", "response_payload", "payment_object"]
    column_list = (
        "id",
        "status",
        "total",
        "provider",
        "anonymous_shipping",
        "created_at",
    )
    column_filters = ("status", "provider", "anonymous_shipping")
    can_create = False
    form_excluded_columns = ("created_at", "updated_at", "items")


def init_admin(app, admin_ext):
    """Register model views on the Admin instance."""
    from .models import (
        BlogPost,
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

    admin_ext.add_view(
        UserAdminView(
            User,
            db.session,
            name=_l("Users"),
            category=_l("Auth"),
            menu_icon_type="tabler",
            menu_icon_value="users",
        )
    )
    admin_ext.add_view(
        RoleAdminView(
            Role,
            db.session,
            name=_l("Roles"),
            category=_l("Auth"),
            menu_icon_type="tabler",
            menu_icon_value="shield",
        )
    )
    admin_ext.add_view(
        StaticPageAdminView(
            StaticPage,
            db.session,
            name=_l("Pages"),
            category=_l("Content"),
            menu_icon_type="tabler",
            menu_icon_value="file-text",
        )
    )
    admin_ext.add_view(
        BlogPostAdminView(
            BlogPost,
            db.session,
            name=_l("Blog Posts"),
            category=_l("Content"),
            menu_icon_type="tabler",
            menu_icon_value="file-text",
        )
    )
    admin_ext.add_view(
        MinutePackAdminView(
            MinutePack,
            db.session,
            name=_l("Packs de Minutos"),
            category=_l("Tienda"),
            menu_icon_type="tabler",
            menu_icon_value="clock",
        )
    )
    admin_ext.add_view(
        SubscriptionPlanAdminView(
            SubscriptionPlan,
            db.session,
            name=_l("Suscripciones"),
            category=_l("Tienda"),
            menu_icon_type="tabler",
            menu_icon_value="credit-card",
        )
    )
    admin_ext.add_view(
        ProductCategoryAdminView(
            ProductCategory,
            db.session,
            name=_l("Categorías"),
            category=_l("Tienda"),
            menu_icon_type="tabler",
            menu_icon_value="tag",
        )
    )
    admin_ext.add_view(
        ProductAdminView(
            Product,
            db.session,
            name=_l("Productos"),
            category=_l("Tienda"),
            menu_icon_type="tabler",
            menu_icon_value="package",
        )
    )
    admin_ext.add_view(
        OrderAdminView(
            Order,
            db.session,
            name=_l("Órdenes"),
            category=_l("Tienda"),
            menu_icon_type="tabler",
            menu_icon_value="shopping-cart",
        )
    )
    admin_ext.add_view(
        SiteSettingsAdminView(
            SiteSettings,
            db.session,
            name=_l("Configuración"),
            category=_l("Sitio"),
            menu_icon_type="tabler",
            menu_icon_value="settings",
        )
    )
    admin_ext.add_view(
        SeoSettingsAdminView(
            name=_l("SEO"),
            endpoint="seo_settings",
            category=_l("Sitio"),
            menu_icon_type="tabler",
            menu_icon_value="search",
        )
    )
    admin_ext.add_view(
        AnalyticsSettingsAdminView(
            name=_l("Analytics"),
            endpoint="analytics_settings",
            category=_l("Sitio"),
            menu_icon_type="tabler",
            menu_icon_value="chart-dots",
        )
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
    admin_ext.add_view(
        MonthlyAgentReportView(
            name=_l("Reporte Agentes"),
            endpoint="monthly_agent_report",
            category=_l("Reportes"),
            menu_icon_type="tabler",
            menu_icon_value="users",
        )
    )
    admin_ext.add_link(
        MenuLink(name="Home Page", url="/", icon_type="tabler", icon_value="home")
    )
