"""Payment provider implementations for nuevo-fonotarot.

``FlowProvider`` is a local implementation that wraps ``pyflowcl`` directly,
working around an API incompatibility between ``merchants`` FlowProvider and
pyflowcl ≥ 2025.2 (which removed ``GenericError`` from its exceptions module).
``KhipuProvider`` is re-exported from the ``merchants`` SDK unchanged.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from merchants.models import CheckoutSession, PaymentState, PaymentStatus, WebhookEvent
from merchants.providers import Provider, UserError

from pyflowcl.Clients import ApiClient
from pyflowcl.Payment import create as flow_create
from pyflowcl.Payment import getStatus as flow_get_status

# Re-export KhipuProvider from merchants (it works with the installed version).
from merchants.providers.khipu import KhipuProvider  # noqa: F401

# Flow status codes: 1=Paid, 2=Rejected, 3=Pending, 4=Cancelled
_FLOW_STATE_MAP: dict[int, PaymentState] = {
    1: PaymentState.SUCCEEDED,
    2: PaymentState.FAILED,
    3: PaymentState.PENDING,
    4: PaymentState.CANCELLED,
}


class FlowProvider(Provider):
    """Flow.cl payment provider compatible with pyflowcl ≥ 2025.2.

    Wraps ``pyflowcl`` directly without depending on
    ``pyflowcl.exceptions.GenericError`` (removed in 2025.2).

    Args:
        api_key: Flow API key.
        api_secret: Flow API secret (HMAC-SHA256 signing).
        api_url: Base URL override (default: ``"https://sandbox.flow.cl/api"``).
        subject: Default payment description shown to the payer.
        confirmation_url: URL Flow calls server-to-server after payment.
    """

    key = "flow"
    name = "Flow.cl"
    author = "nuevo-fonotarot"
    version = "1.0.0"
    description = "Flow.cl payment gateway for Chile (pyflowcl 2025.2+ compatible)."
    url = "https://www.flow.cl"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        api_url: str = "https://sandbox.flow.cl/api",
        subject: str = "Fonotarot - Compra",
        confirmation_url: str = "",
    ) -> None:
        self._client = ApiClient(
            api_url=api_url,
            api_key=api_key,
            api_secret=api_secret,
        )
        self._subject = subject
        self._confirmation_url = confirmation_url

    def create_checkout(
        self,
        amount: Decimal,
        currency: str,
        success_url: str,
        cancel_url: str,
        metadata: dict[str, Any] | None = None,
    ) -> CheckoutSession:
        amount_int = int(amount)
        payment_data: dict[str, Any] = {
            "amount": amount_int,
            "commerceOrder": (metadata or {}).get("order_id", ""),
            "currency": currency.upper(),
            "subject": self._subject,
            "urlReturn": success_url,
            "urlConfirmation": self._confirmation_url or success_url,
        }
        try:
            response = flow_create(self._client, payment_data)
        except Exception as exc:
            raise UserError(str(exc)) from exc

        redirect_url = (
            f"{response.url}?token={response.token}"
            if response.url and response.token
            else ""
        )
        return CheckoutSession(
            session_id=str(response.token or ""),
            redirect_url=redirect_url,
            provider=self.key,
            amount=amount,
            currency=currency,
            metadata=metadata or {},
            raw={"token": response.token, "flowOrder": getattr(response, "flowOrder", None)},
        )

    def get_payment(self, payment_id: str) -> PaymentStatus:
        try:
            status = flow_get_status(self._client, payment_id)
        except Exception as exc:
            raise UserError(str(exc)) from exc

        state = _FLOW_STATE_MAP.get(status.status or 0, PaymentState.UNKNOWN)
        return PaymentStatus(
            payment_id=payment_id,
            state=state,
            provider=self.key,
            amount=Decimal(str(status.amount)) if status.amount is not None else None,
            currency=status.currency,
            raw={
                "status": status.status,
                "commerceOrder": status.commerceOrder,
                "payer": getattr(status, "payer", None),
            },
        )

    def parse_webhook(self, payload: bytes, headers: dict[str, str]) -> WebhookEvent:
        token = ""
        try:
            data: dict[str, Any] = json.loads(payload)
            token = data.get("token", "")
        except ValueError:
            from urllib.parse import parse_qs
            qs = parse_qs(payload.decode(errors="replace"))
            token = (qs.get("token") or [""])[0]
            data = {"token": token}

        return WebhookEvent(
            event_id=token or None,
            event_type="payment.notification",
            payment_id=token or None,
            state=PaymentState.UNKNOWN,
            provider=self.key,
            raw=data,
        )
