"""Flask-Admin configuration using Flask-Security for authentication."""

from flask import redirect, request, url_for
from flask_admin import AdminIndexView, expose
from flask_admin.contrib.sqla import ModelView
from flask_security import current_user

from app.extensions import db


class SecureAdminIndexView(AdminIndexView):
    """Admin index view that requires an authenticated user with the 'admin' role."""

    @expose("/")
    def index(self):
        if not current_user.is_authenticated or not current_user.has_role("admin"):
            return redirect(url_for("security.login"))
        return super().index()


class SecureModelView(ModelView):
    """ModelView accessible only to authenticated users with the 'admin' role."""

    def is_accessible(self):
        return current_user.is_authenticated and current_user.has_role("admin")

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


def init_admin(app, admin_ext):
    """Register model views on the Admin instance."""
    from app.models import Role, User

    admin_ext.add_view(UserAdminView(User, db.session, name="Users", category="Auth"))
    admin_ext.add_view(RoleAdminView(Role, db.session, name="Roles", category="Auth"))
