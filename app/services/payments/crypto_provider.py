from __future__ import annotations

import json
from decimal import Decimal

from app.config import get_settings
from app.services.payments import nowpayments
from app.services.payments.base import PaymentProvider, WebhookEvent


class CryptoProvider(PaymentProvider):
    async def create_invoice(self, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return await nowpayments.create_invoice(order_id=order_id, amount=amount_usd, description=description)

    def verify_webhook(self, raw_body: bytes, signature: str) -> WebhookEvent | None:
        settings = get_settings()
        if not nowpayments.verify_ipn_signature(raw_body, signature, settings.nowpayments_ipn_secret):
            return None
        try:
            data = json.loads(raw_body)
        except json.JSONDecodeError:
            return None
        order_id = data.get("order_id")
        payment_id = data.get("payment_id") or data.get("id")
        if not order_id or not payment_id:
            return None
        paid = data.get("actually_paid")
        return WebhookEvent(
            provider_payment_id=str(payment_id),
            order_id=str(order_id),
            raw_status=data.get("payment_status", ""),
            paid_amount=Decimal(str(paid)) if paid is not None else None,
        )
