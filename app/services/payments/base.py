from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class WebhookEvent:
    provider_payment_id: str
    order_id: str
    raw_status: str
    paid_amount: Decimal | None  # in the invoice's pay_currency, not USD - see Payment.paid_amount


class PaymentProvider(ABC):
    """Exactly two methods, deliberately - a provider's job is talking to
    its gateway (create an invoice, verify a signature), never Homeland
    domain logic like which IBSng call to make. See
    docs/superpowers/specs/2026-09-16-crypto-payment-design.md §4 for why
    this differs from the parent spec's original sketch."""

    @abstractmethod
    async def create_invoice(self, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        """Returns (url to hand the buyer, provider's own payment id)."""

    @abstractmethod
    def verify_webhook(self, raw_body: bytes, signature: str) -> WebhookEvent | None:
        """Verifies signature, parses the callback. None if invalid."""
