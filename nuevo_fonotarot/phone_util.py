"""Custom Flask-Security UsernameUtil that validates E.164 phone numbers.

The ``username`` field stores the phone number in E.164 format without the
leading ``+`` sign (e.g. ``56912345678``).  Users may type with or without the
``+`` prefix — it is stripped during normalisation.

Validation rule (mirrors the inline check in ``content/views.py``):
    * digits only, no spaces or symbols
    * length between 10 and 13 characters (after stripping the leading ``+``)
"""

from flask_security.username_util import UsernameUtil


class PhoneUsernameUtil(UsernameUtil):
    """UsernameUtil subclass that treats the username as an E.164 phone number."""

    def normalize(self, username: str) -> str:
        """Strip whitespace and the optional leading ``+``, return digits only."""
        if not username:
            return ""
        return username.strip().lstrip("+")

    def check_username(self, username: str) -> str | None:
        """Return an error message if *username* is not a valid E.164 phone.

        Accepts digits only, 10–13 characters (after ``+`` has been stripped by
        :meth:`normalize`).  Returns ``None`` when valid.
        """
        if not username.isdigit() or not (10 <= len(username) <= 13):
            return (
                "Ingresa un número de teléfono válido "
                "(solo dígitos, sin +, entre 10 y 13 dígitos)."
            )
        return None

    def validate(self, username: str) -> tuple[str | None, str | None]:
        """Strip leading ``+`` before delegating to the parent validator."""
        if username:
            username = username.strip().lstrip("+")
        return super().validate(username)
