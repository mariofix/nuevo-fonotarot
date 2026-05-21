"""Forms for the account blueprint."""

from flask import current_app
from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import EmailField, PasswordField, StringField, SubmitField, validators


class ClaimAccountForm(FlaskForm):
    """Form for captured (telephone) customers to create their web account.

    Identity is verified against the Firenze telephony platform using the
    provided email and phone number before the account is created.
    """

    email = EmailField(
        _l("Email"),
        validators=[
            validators.DataRequired(message=_l("El email es obligatorio.")),
            validators.Email(message=_l("Ingresa un email válido.")),
        ],
        render_kw={"placeholder": "tu@email.com", "autocomplete": "email"},
    )

    phone = StringField(
        _l("Teléfono"),
        validators=[
            validators.DataRequired(message=_l("El teléfono es obligatorio.")),
            validators.Regexp(
                r"^\d{7,15}$",
                message=_l("Ingresa el teléfono en formato E.164 sin el signo + (ej: 56912345678)."),
            ),
        ],
        render_kw={"placeholder": "56912345678", "autocomplete": "tel", "type": "tel"},
    )

    password = PasswordField(
        _l("Contraseña"),
        validators=[
            validators.DataRequired(message=_l("La contraseña es obligatoria.")),
        ],
        render_kw={"placeholder": "••••••••", "autocomplete": "new-password"},
    )

    password_confirm = PasswordField(
        _l("Confirmar contraseña"),
        validators=[
            validators.DataRequired(message=_l("Confirma tu contraseña.")),
            validators.EqualTo("password", message=_l("Las contraseñas no coinciden.")),
        ],
        render_kw={"placeholder": "••••••••", "autocomplete": "new-password"},
    )

    submit = SubmitField(_l("Activar mi cuenta"))

    def validate_password(self, field: PasswordField) -> None:
        """Enforce the minimum password length configured for the app."""
        from flask_babel import _

        min_length: int = current_app.config.get("SECURITY_PASSWORD_LENGTH_MIN", 8)
        if field.data and len(field.data) < min_length:
            raise validators.ValidationError(_("La contraseña debe tener al menos %(n)d caracteres.", n=min_length))
