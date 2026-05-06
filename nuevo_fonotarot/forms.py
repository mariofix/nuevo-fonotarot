"""Custom Flask-Security forms for passwordless authentication."""


def customize_unified_signin_form(form):
    """
    Customize the unified signin form to filter method choices.
    Only shows methods that are in SECURITY_US_ENABLED_METHODS.
    """
    from flask import current_app

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
    
    return form




