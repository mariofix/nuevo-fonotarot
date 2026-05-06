"""User-related actions that can be run independently or during lifecycle events."""

from .extensions import db, user_datastore
from .firenze import search_client
from .log import get_logger
from .models import User
from .notifications import notify_new_user_registration

logger = get_logger(__name__)


def process_user_registration(user: User) -> bool:
    """Execute post-registration steps for a newly registered user.

    Performs all necessary setup after user registration, including:
    - Sending a Telegram notification about the new registration
    - Syncing username (phone) into the phone field if not already set
    - Looking up and saving Firenze client_id if available
    - Adding user to 'clientes' role if client_id is found

    Args:
        user: The newly registered user.

    Returns:
        True if Firenze client_id was found and saved, False otherwise.
        Note: This returns False if no client_id was found (not an error—just
        means Firenze has no record for this user yet).
    """
    logger.info(
        "process_user_registration: starting for user=%s (email=%r phone=%r)",
        user.id,
        user.email,
        user.username,
    )
    
    # Send Telegram notification about new registration
    try:
        notify_new_user_registration(email=user.email, phone=user.phone or user.username)
        logger.debug(
            "process_user_registration: Telegram notification sent for user=%s",
            user.id,
        )
    except Exception:
        logger.exception(
            "process_user_registration: failed to send Telegram notification for user=%s",
            user.id,
        )
    
    # Copy username → phone if phone is blank (non-enforced convenience sync).
    if user.username and not user.phone:
        user.phone = user.username
        logger.debug(
            "process_user_registration: synced username to phone field for user=%s (phone=%r)",
            user.id,
            user.phone,
        )

    try:
        logger.debug(
            "process_user_registration: looking up Firenze client for user=%s (email=%r phone=%r)",
            user.id,
            user.email,
            user.phone or user.username,
        )
        client_id = search_client(email=user.email, phone=user.phone or user.username)
        
        if client_id is not None:
            user.firenze_client_id = client_id
            logger.debug(
                "process_user_registration: found Firenze client_id=%s for user=%s",
                client_id,
                user.id,
            )
            
            _assign_clientes_role(user)
            db.session.commit()
            logger.info(
                "process_user_registration: saved Firenze client_id=%s and assigned 'clientes' role for user=%s (email=%r phone=%r)",
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
            "process_user_registration: failed for user=%s (email=%r phone=%r)",
            user.id,
            user.email,
            user.phone or user.username,
        )
        return False


def _assign_clientes_role(user: User) -> None:
    """Add user to the 'clientes' role if not already assigned.

    Args:
        user: The user to assign the 'clientes' role to.
    """
    logger.debug(
        "_assign_clientes_role: looking up 'clientes' role for user=%s",
        user.id,
    )
    
    clientes_role = user_datastore.find_role("clientes")
    if not clientes_role:
        logger.error(
            "_assign_clientes_role: 'clientes' role not found in database (user=%s)",
            user.id,
        )
        return
    
    if clientes_role not in user.roles:
        user_datastore.add_role_to_user(user, clientes_role)
        logger.info(
            "_assign_clientes_role: added 'clientes' role to user=%s",
            user.id,
        )
        logger.debug(
            "_assign_clientes_role: user=%s now has roles: %s",
            user.id,
            [role.name for role in user.roles],
        )
    else:
        logger.debug(
            "_assign_clientes_role: user=%s already has 'clientes' role",
            user.id,
        )

