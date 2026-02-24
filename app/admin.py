"""Flask-Admin configuration with session-based authentication."""

from flask import flash, redirect, request, session, url_for
from flask_admin import AdminIndexView, expose
from flask_admin.contrib.sqla import ModelView

from app.extensions import db


def _is_authenticated() -> bool:
    return session.get("admin_authenticated", False)


class AuthAdminIndexView(AdminIndexView):
    """Custom index view that gates access behind a login form."""

    @expose("/")
    def index(self):
        if not _is_authenticated():
            return redirect(url_for(".login_view"))
        return super().index()

    @expose("/login/", methods=["GET", "POST"])
    def login_view(self):
        from app.models import User

        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = db.session.execute(
                db.select(User).where(User.username == username, User.is_active.is_(True))
            ).scalar_one_or_none()

            if user and user.is_admin and user.check_password(password):
                session["admin_authenticated"] = True
                session["admin_user"] = user.username
                return redirect(url_for(".index"))
            flash("Invalid credentials.", "error")

        return self.render("admin/login.html")

    @expose("/logout/")
    def logout_view(self):
        session.pop("admin_authenticated", None)
        session.pop("admin_user", None)
        return redirect(url_for(".login_view"))


class SecureModelView(ModelView):
    """ModelView that requires admin authentication."""

    def is_accessible(self):
        return _is_authenticated()

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for("admin.login_view", next=request.url))


class UserAdminView(SecureModelView):
    """Admin view for the User model."""

    column_list = ("username", "email", "is_admin", "is_active", "created_at")
    column_searchable_list = ("username", "email")
    column_filters = ("is_admin", "is_active")
    form_excluded_columns = ("password_hash", "created_at")


def init_admin(app, admin_ext):
    """Register model views on the Admin instance."""
    from app.models import User

    admin_ext.add_view(UserAdminView(User, db.session, name="Users", category="Auth"))
