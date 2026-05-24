"""Domain services for digital prepaid gift cards."""

from datetime import UTC, datetime
from secrets import choice
from string import ascii_uppercase, digits

from ...extensions import db
from ...firenze import post_purchase
from ...log import get_logger
from ...models import GiftCard, GiftCardProduct, Order, OrderItemType, User

logger = get_logger(__name__)

_CODE_ALPHABET = ascii_uppercase + digits
_CODE_LENGTH = 12


def _normalize_code(raw: str) -> str:
    return "".join(ch for ch in raw.upper().strip() if ch in _CODE_ALPHABET)


def _new_code() -> str:
    return "".join(choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))


def generate_unique_gift_code() -> str:
    """Generate a unique, human-friendly gift-card code."""
    for _ in range(30):
        candidate = _new_code()
        exists = GiftCard.query.filter_by(code=candidate).first()
        if exists is None:
            return candidate
    raise RuntimeError("No fue posible generar un código de tarjeta único.")


def issue_gift_cards_for_order(order: Order) -> int:
    """Create missing gift-card codes for paid order gift-card items."""
    issued_count = 0
    request_payload = order.request_payload if isinstance(order.request_payload, dict) else {}
    recipient_email = (request_payload.get("gift_card_recipient_email") or "").strip() or None

    for item in list(order.items):
        if item.item_type != OrderItemType.GIFT_CARD.value:
            continue

        product = db.session.get(GiftCardProduct, int(item.item_id))
        if product is None:
            logger.warning(
                "issue_gift_cards_for_order: missing gift product id=%s for order=%s",
                item.item_id,
                order.id,
            )
            continue

        quantity = max(int(item.quantity or 1), 1)
        existing = GiftCard.query.filter_by(order_id=order.id, gift_card_product_id=product.id).count()
        missing = max(0, quantity - existing)
        for _ in range(missing):
            gift_card = GiftCard(
                code=generate_unique_gift_code(),
                gift_card_product_id=product.id,
                order_id=order.id,
                purchaser_email=order.shipping_email or order.email,
                recipient_email=recipient_email,
                status="issued",
            )
            db.session.add(gift_card)
            issued_count += 1

    if issued_count:
        db.session.commit()
        logger.info("issue_gift_cards_for_order: issued=%s order=%s", issued_count, order.id)

    return issued_count


def redeem_gift_card(*, gift_card: GiftCard, user: User) -> tuple[bool, str]:
    """Redeem *gift_card* to *user* by posting minutes to Firenze."""
    if gift_card.status == "redeemed":
        return False, "Esta tarjeta ya fue canjeada."

    product = gift_card.gift_card_product
    if product is None:
        return False, "La tarjeta no está asociada a un producto válido."

    seconds_to_add = int(product.minutes) * 60
    transaction_id = f"gc_{gift_card.code}_{int(datetime.now(UTC).timestamp())}"
    response = post_purchase(
        client_id=user.firenze_client_id,
        segundos=seconds_to_add,
        transaction_id=transaction_id,
        name=user.full_name,
        email=user.email,
        ani=user.username or user.phone,
    )
    if response is None:
        logger.warning("redeem_gift_card: Firenze post_purchase failed gift_card=%s user=%s", gift_card.id, user.id)
        return False, "No fue posible canjear la tarjeta en este momento."

    if isinstance(response, dict):
        response_client_id = response.get("client_id")
        if response_client_id and not user.firenze_client_id:
            try:
                user.firenze_client_id = int(response_client_id)
            except TypeError, ValueError:
                logger.warning(
                    "redeem_gift_card: invalid client_id in response gift_card=%s user=%s client_id=%r",
                    gift_card.id,
                    user.id,
                    response_client_id,
                )

    gift_card.status = "redeemed"
    gift_card.redeemed_by_user_id = user.id
    gift_card.redeemed_at = datetime.now(UTC)
    gift_card.redemption_order_id = transaction_id
    db.session.commit()
    logger.info("redeem_gift_card: redeemed gift_card=%s by user=%s", gift_card.id, user.id)
    return True, "Tarjeta canjeada correctamente."


def normalize_input_code(raw: str) -> str:
    """Normalize user input code to canonical uppercase representation."""
    return _normalize_code(raw)
