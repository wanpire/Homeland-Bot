from __future__ import annotations

import json
from decimal import Decimal

from app.config import get_settings
from app.services.payments import nowpayments
from app.services.payments.base import PayabilityReport, PaymentProvider, WebhookEvent
from app.services.payments.currencies import PayCurrency
from app.services.payments.minimums import get_minimums


class CryptoProvider(PaymentProvider):
    async def payable_currencies(self, amount_usd: Decimal) -> PayabilityReport:
        """A coin is payable when this amount clears its current minimum.
        A stale minimum still counts - it is a real NOWPayments number,
        only older than the refresh window; only a coin we have no number
        for at all lands in `unknown`."""
        payable: list[PayCurrency] = []
        too_low: list[tuple[PayCurrency, Decimal]] = []
        unknown: list[PayCurrency] = []
        for minimum in await get_minimums():
            if minimum.min_usd is None:
                unknown.append(minimum.currency)
            elif amount_usd >= minimum.min_usd:
                payable.append(minimum.currency)
            else:
                too_low.append((minimum.currency, minimum.min_usd))
        return PayabilityReport(payable=payable, too_low=too_low, unknown=unknown)

    async def create_invoice(
        self, *, order_id: str, amount_usd: Decimal, description: str, pay_currency: str | None = None
    ) -> tuple[str, str]:
        return await nowpayments.create_invoice(
            order_id=order_id, amount=amount_usd, description=description, pay_currency=pay_currency
        )

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
