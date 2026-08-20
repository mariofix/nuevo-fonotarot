"""Signal-facing post-payment processes."""

from .actions import post_purchase_process
from .log import get_logger

logger = get_logger(__name__)


def _handle_payment_webhook_finished(_sender, *, event, **kwargs) -> None:
    """Signal receiver that runs after flask-merchants finishes webhook dispatch."""
    logger.debug(f"_handle_payment_webhook_finished: Called with {_sender=} {event=} {kwargs=}")
    logger.debug(
        f"_handle_payment_webhook_finished: Event {event.payment_id=} Info "
        f"{event.provider=} {event.event_type=} {event.state=}"
    )

    post_purchase_process(transaction_id=event.payment_id)
