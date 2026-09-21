from __future__ import annotations

from decimal import Decimal

from app.services.payments import plisio
from app.services.payments.base import PaymentProvider, WebhookEvent


class CryptoProvider(PaymentProvider):
    """Plisio-backed crypto payments. The buyer chooses their coin on
    Plisio's own invoice page (see plisio.create_invoice), so nothing
    here needs to know about individual coins or their minimums."""

    async def create_invoice(self, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return await plisio.create_invoice(order_id=order_id, amount=amount_usd, description=description)

    def verify_webhook(self, raw_body: bytes, signature: str) -> WebhookEvent | None:
        """`signature` is accepted for interface compatibility and
        deliberately unused: Plisio carries its verify_hash INSIDE the
        body, not in a header (unlike NOWPayments' x-nowpayments-sig)."""
        payload = plisio.verify_callback(raw_body)
        if payload is None:
            return None

        order_id = payload.get("order_number")
        txn_id = payload.get("txn_id")
        status = payload.get("status")
        if not order_id or not txn_id or not status:
            return None

        amount = payload.get("amount")
        try:
            paid_amount = Decimal(str(amount)) if amount not in (None, "") else None
        except (ArithmeticError, ValueError):
            paid_amount = None

        return WebhookEvent(
            provider_payment_id=str(txn_id),
            order_id=str(order_id),
            raw_status=str(status),
            paid_amount=paid_amount,
        )
