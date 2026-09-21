from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal

from app.services.payments.currencies import PayCurrency

PAYABLE = "payable"
UNPAYABLE = "unpayable"
UNAVAILABLE = "unavailable"


@dataclass
class WebhookEvent:
    provider_payment_id: str
    order_id: str
    raw_status: str
    paid_amount: Decimal | None  # in the invoice's pay_currency, not USD - see Payment.paid_amount


@dataclass
class PayabilityReport:
    """Which accepted coins can pay one exact USD amount right now.

    `unknown` exists to keep two very different failures apart: "this
    plan costs less than every network minimum" (the buyer should pick a
    bigger plan) versus "we couldn't ask NOWPayments" (the buyer should
    try again later). Collapsing them would tell a customer their plan
    is too cheap during an outage."""

    payable: list[PayCurrency]
    too_low: list[tuple[PayCurrency, Decimal]]
    unknown: list[PayCurrency]

    @property
    def status(self) -> str:
        if self.payable:
            return PAYABLE
        return UNAVAILABLE if self.unknown else UNPAYABLE

    @property
    def lowest_minimum(self) -> Decimal | None:
        """The cheapest minimum we know of, for the "too low" message -
        the smallest price bump that would make this plan payable."""
        return min((minimum for _, minimum in self.too_low), default=None)


class PaymentProvider(ABC):
    """Exactly two methods, deliberately - a provider's job is talking to
    its gateway (create an invoice, verify a signature), never Homeland
    domain logic like which IBSng call to make. See
    docs/superpowers/specs/2026-09-16-crypto-payment-design.md §4 for why
    this differs from the parent spec's original sketch."""

    @abstractmethod
    async def payable_currencies(self, amount_usd: Decimal) -> PayabilityReport:
        """Which accepted coins can pay this exact amount right now."""

    @abstractmethod
    async def create_invoice(
        self, *, order_id: str, amount_usd: Decimal, description: str, pay_currency: str | None = None
    ) -> tuple[str, str]:
        """Returns (url to hand the buyer, provider's own payment id).
        pay_currency locks the hosted page to a single coin."""

    @abstractmethod
    def verify_webhook(self, raw_body: bytes, signature: str) -> WebhookEvent | None:
        """Verifies signature, parses the callback. None if invalid."""
