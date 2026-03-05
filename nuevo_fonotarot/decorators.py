"""Auth decorators that render a modal gate instead of redirecting.

Instead of the classic ``redirect(url_for('security.login'))`` pattern,
these decorators return the current page with the content obfuscated and a
login / access-denied modal overlaid on top.  The URL never changes, so the
user immediately sees *what* they are missing.
"""

from functools import wraps

from flask import render_template, request
from flask_security import current_user


def login_required_modal(f):
    """Return an obfuscated gate page when the user is not authenticated.

    The original view is *not* called — a skeleton placeholder is rendered
    behind a login modal instead.  The ``next`` parameter is pre-filled so
    Flask-Security redirects back after a successful login.
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return (
                render_template(
                    "auth/login_gate.html",
                    next_url=request.url,
                ),
                401,
            )
        return f(*args, **kwargs)

    return decorated_function


def accepted_roles(*roles):
    """Return a forbidden gate page when the user lacks the required role(s).

    Unauthenticated users see the login gate (same as ``login_required_modal``).
    Authenticated users who do not hold *any* of the required roles see the
    forbidden gate instead.

    Usage::

        @accepted_roles("admin", "staff")
        def my_view():
            ...
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return (
                    render_template(
                        "auth/login_gate.html",
                        next_url=request.url,
                    ),
                    401,
                )
            if not any(current_user.has_role(role) for role in roles):
                return (
                    render_template(
                        "auth/forbidden_gate.html",
                        required_roles=roles,
                    ),
                    403,
                )
            return f(*args, **kwargs)

        return decorated_function

    return decorator
