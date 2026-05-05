"""User-related actions that can be run independently or during lifecycle events."""

from .extensions import db
from .firenze import search_client
from .log import get_logger
from .models import User

logger = get_logger(__name__)


def process_user_registration(user: User) -> bool:
    """Execute post-registration steps for a newly registered user.

    Performs all necessary setup after user registration, including:
    - Syncing username (phone) into the phone field if not already set
    - Looking up and saving Firenze client_id if available

    Args:
        user: The newly registered user.

    Returns:
        True if Firenze client_id was found and saved, False otherwise.
        Note: This returns False if no client_id was found (not an error—just
        means Firenze has no record for this user yet).
    """
    # Copy username → phone if phone is blank (non-enforced convenience sync).
    if user.username and not user.phone:
        user.phone = user.username

    try:
        client_id = search_client(email=user.email, phone=user.phone or user.username)
        if client_id is not None:
            user.firenze_client_id = client_id
            db.session.commit()
            logger.info(
                "process_user_registration: saved Firenze client_id=%s for user=%s (email=%r phone=%r)",
                client_id,
                user.id,
                user.email,
                user.phone,
            )
            return True
        else:
            logger.debug(
                "process_user_registration: no Firenze client_id found for user=%s (email=%r phone=%r)",
                user.id,
                user.email,
                user.phone,
            )
            return False
    except Exception:
        logger.exception(
            "process_user_registration: failed for user=%s", user.id
        )
        return False
