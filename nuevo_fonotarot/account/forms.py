"""Forms for the account blueprint."""

from flask import current_app
from flask_wtf import FlaskForm
from wtforms import EmailField, PasswordField, StringField, SubmitField
from wtforms import validators


class ClaimAccountForm(FlaskForm):
    """Form for captured (telephone) customers to create their web account.

    Identity is verified against the Firenze telephony platform using the
    provided email and phone number before the account is created.
    """

    email = EmailField(
        "Email",
        validators=[
            validators.DataRequired(message="El email es obligatorio."),
            validators.Email(message="Ingresa un email válido."),
        ],
        render_kw={"placeholder": "tu@email.com", "autocomplete": "email"},
    )

    phone = StringField(
        "Teléfono",
        validators=[
            validators.DataRequired(message="El teléfono es obligatorio."),
            validators.Regexp(
                r"^\d{7,15}$",
                message="Ingresa el teléfono en formato E.164 sin el signo + (ej: 56912345678).",
            ),
        ],
        render_kw={"placeholder": "56912345678", "autocomplete": "tel", "type": "tel"},
    )

    password = PasswordField(
        "Contraseña",
        validators=[
            validators.DataRequired(message="La contraseña es obligatoria."),
        ],
        render_kw={"placeholder": "••••••••", "autocomplete": "new-password"},
    )

    password_confirm = PasswordField(
        "Confirmar contraseña",
        validators=[
            validators.DataRequired(message="Confirma tu contraseña."),
            validators.EqualTo("password", message="Las contraseñas no coinciden."),
        ],
        render_kw={"placeholder": "••••••••", "autocomplete": "new-password"},
    )

    submit = SubmitField("Activar mi cuenta")

    def validate_password(self, field: PasswordField) -> None:
        """Enforce the minimum password length configured for the app."""
        min_length: int = current_app.config.get("SECURITY_PASSWORD_LENGTH_MIN", 8)
        if field.data and len(field.data) < min_length:
            raise validators.ValidationError(
                f"La contraseña debe tener al menos {min_length} caracteres."
            )
