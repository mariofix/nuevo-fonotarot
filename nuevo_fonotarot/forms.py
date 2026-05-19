"""Custom Flask-Security forms for passwordless authentication."""


def customize_unified_signin_form(form):
    """
    Customize the unified signin form to filter method choices
    and add conditional passcode validation.
    
    Only shows methods that are in SECURITY_US_ENABLED_METHODS.
    Skips passcode validation when user is sending a code (not verifying).
    """
    from flask import current_app, request
    from flask_babel import _
    from wtforms import ValidationError

    # Filter the chosen_method RadioField choices to only show enabled methods
    enabled_methods = current_app.config.get("SECURITY_US_ENABLED_METHODS", ["email"])
    method_labels = {
        "email": "Via email",
        "sms": "Via SMS",
        "authenticator": "Via authenticator",
    }
    
    # Update choices to only include enabled methods
    form.chosen_method.choices = [
        (method, method_labels.get(method, method))
        for method in enabled_methods
        if method in method_labels
    ]
    
    # Set the first enabled method as default
    if form.chosen_method.choices:
        form.chosen_method.data = form.chosen_method.choices[0][0]
    
    # Add custom validator for passcode: only validate if NOT sending code
    original_passcode_validators = form.passcode.validators
    
    def conditional_passcode_validator(form, field):
        """Skip passcode validation when sending code (not verifying)."""
        # Check if submit_send_code button was clicked
        is_sending_code = 'submit_send_code' in request.form
        
        # Only validate passcode if NOT sending code
        if not is_sending_code and not field.data:
            raise ValidationError(_("Passcode is required for verification"))
    
    # Keep original validators but add our conditional check at the start
    form.passcode.validators = [conditional_passcode_validator]
    
    return form




