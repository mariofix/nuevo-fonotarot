"""User-related actions that can be run independently or during lifecycle events."""

from __future__ import annotations

from .extensions import db, user_datastore
from .firenze import search_client
from .log import get_logger
from .models import User, OrderStatus, OrderItemType, MinutePack, Order, OrderItem
from .notifications import notify_new_user_registration

logger = get_logger(__name__)


class _CheckoutRegistrationForm:
    """Minimal form adapter for Flask-Security ``register_user``."""

    def __init__(self, email: str, phone: str) -> None:
        self._email = email
        self._phone = phone

    def to_dict(self, only_user: bool = False) -> dict:
        payload = {
            "email": self._email,
            "username": self._phone,
            "phone": self._phone,
            # Passwordless account: password is intentionally unset.
            "password": None,
        }
        return payload


def register_checkout_account(email: str, phone: str) -> tuple[User, bool]:
    """Create (or fetch) a user from checkout data using Flask-Security flow.

    This uses Flask-Security's ``register_user`` helper so standard registration
    side effects still happen (signals, confirmation token generation, welcome
    email dispatch, and unified-signin setup for email codes).

    Returns:
        A tuple ``(user, created)`` where ``created`` is ``True`` only when a
        new account was created.
    """
    from flask_security.registerable import register_user
    from sqlalchemy.exc import IntegrityError

    normalized_email = email.strip().lower()
    normalized_phone = phone.strip().lstrip("+")

    if not normalized_phone:
        raise ValueError("missing_phone")
    if not normalized_phone.isdigit() or not (10 <= len(normalized_phone) <= 13):
        raise ValueError("invalid_phone")

    existing = User.query.filter_by(email=normalized_email).first()
    if existing is not None:
        return existing, False

    form = _CheckoutRegistrationForm(email=normalized_email, phone=normalized_phone)
    try:
        user = register_user(form)
    except IntegrityError:
        db.session.rollback()
        existing_after_conflict = User.query.filter_by(email=normalized_email).first()
        if existing_after_conflict is not None:
            return existing_after_conflict, False
        raise

    db.session.commit()
    logger.info(
        "register_checkout_account: created user=%s from checkout email=%r",
        user.id,
        normalized_email,
    )
    return user, True


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
    changed = False

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
        changed = True
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
            user.username or user.phone,
        )
        client_id = search_client(email=user.email, phone=user.username or user.phone)
        
        if client_id is not None:
            user.firenze_client_id = client_id
            changed = True
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
            if changed:
                db.session.commit()
            logger.debug(
                "process_user_registration: no Firenze client_id found for user=%s (email=%r phone=%r)",
                user.id,
                user.email,
                user.phone,
            )
            return False
    except Exception:
        if changed:
            db.session.commit()
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

def post_purchase_process(order_id: int) -> None:
    """Processes that run after a paid purchase
    
    This process does the following:
    - Find client_id in firenze if not in the order
    - For MinutePacks, firenze endpoint complete payment is called
    - User enail is sent if configured
    - Admin email is sent
    - Telegram/Whatsapp notification

    Args:
        order_id: order that is ready to be fulfilled, mostly digital goods.
    """
    

    logger.debug(f"Trying to process order_id: {order_id}")

    if not order_id:
        logger.warning("post_purchase_process: an order_id is needed.")
        return

    order = Order.query.filter_by(id=order_id).first()

    if not order:
        logger.warning(f"post_purchase_process: order_id={order_id} is not found.")
        return

    if order.state != "succeeded":
        logger.warning(f"post_purchase_process: {order_id=} is {order.state=}")
        return

    if not order.firenze_client_id:
        client_id = search_client(ani=order.shipping_phone)