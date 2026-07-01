"""Flask-Admin configuration using Flask-Security for authentication."""

import json
import os
from datetime import date

from flask import jsonify, redirect, request, url_for
from flask_admin import AdminIndexView, BaseView, expose
from flask_admin.actions import action
from flask_admin.contrib.fileadmin import FileAdmin
from flask_admin.contrib.sqla import ModelView
from flask_admin.menu import MenuLink
from flask_admin_tabler import JsonColumnsMixin, tabler_bool_formatter
from flask_babel import lazy_gettext as _l
from flask_security import current_user

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

    def is_accessible(self):
        return current_user and current_user.is_authenticated and current_user.has_role("admin")

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for("security.login", next=request.url))

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
        return current_user and current_user.is_authenticated and current_user.has_role("admin")

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for("security.login", next=request.url))

    @expose("/", methods=["GET"])
    def index(self):
        today = date.today()
        try:
            year = int(request.args.get("year", today.year))
            month = int(request.args.get("month", today.month))
        except ValueError, TypeError:
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
        except ValueError, TypeError:
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

    column_list = ("name", "description")
    column_searchable_list = ("name",)


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


class SiteSettingsAdminView(JsonColumnsMixin, SecureModelView):
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


class OrderAdminView(JsonColumnsMixin, SecureModelView):
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
    column_default_sort = ("id", True)

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
