---
name: payment-provider-abstraction
description: Homeland's implemented PaymentProvider abstraction - CryptoProvider over NOWPayments, the per-coin payability check that keeps low-priced plans payable, pay_currency-locked invoices, and the IPN webhook contract. Use when touching app/services/payments/*, app/webhook.py, or any Buy/Renew step that charges money.
---

# Payment Provider Abstraction (Homeland)

This is **built and live**. Read the real code first:
`app/services/payments/{base,crypto_provider,nowpayments,minimums,currencies,service}.py`
and `app/webhook.py`. This skill records the rules that are easy to break
and expensive to get wrong. Designs:
`docs/superpowers/specs/2026-09-16-crypto-payment-design.md` and
`docs/superpowers/specs/2026-09-21-crypto-payability-design.md`.

## The interface (`app/services/payments/base.py`)

```python
class PaymentProvider(ABC):
    async def payable_currencies(self, amount_usd: Decimal) -> PayabilityReport
    async def create_invoice(self, *, order_id, amount_usd, description, pay_currency=None) -> tuple[str, str]
    def verify_webhook(self, raw_body: bytes, signature: str) -> WebhookEvent | None
```

Three methods, deliberately. A provider talks to its gateway; it never
performs Homeland domain logic (no IBSng calls, no account creation).
Confirming a payment lives in `service.activate_finished_payment`, called
only from the webhook route - see the crypto spec §4 for why
`on_payment_confirmed` is deliberately NOT a provider method.

## Never hardcode a coin's minimum

NOWPayments enforces a per-coin minimum payment amount that drifts with
network fees, and several Homeland plans sit near it. Every minimum comes
from `GET /v1/min-amount` at runtime via
`app/services/payments/minimums.py`, cached in Redis for 10 minutes with a
6-hour stale fallback. Rules:

- Accepted coins come from `Settings.nowpayments_pay_currency_list`
  (`NOWPAYMENTS_PAY_CURRENCIES` in `.env`), never a literal list in a
  handler. Adding TON is a `.env` change plus an optional label in
  `currencies.py`.
- A handler asks `service.check_payability(amount)` and renders the
  resulting `PayabilityReport` through
  `app/bot/handlers/_payability.py`'s `render_payability`. Never compare a
  price against a number in handler code.
- `min_amount` and `fiat_equivalent` are NOT interchangeable:
  `min_amount` is in the coin's own units, `fiat_equivalent` is the USD
  figure. `get_min_amount` returns the latter and omits `currency_to`, so
  NOWPayments computes against the dashboard's outcome wallet.
- Any new checkout path must price from `service.quote_amount(session,
  plan)`, the same function the chooser uses. Pricing the chooser and the
  invoice separately reintroduces the dead end this design removed.

## Three outcomes, three different messages

`PayabilityReport.status` distinguishes failures that look alike and are
not:

- `payable` - at least one coin clears the amount: show the chooser.
- `unpayable` - every minimum is known and higher than the price: tell the
  buyer the plan is too cheap and route them to a pricier plan.
- `unavailable` - we could not reach NOWPayments for some coin and none of
  the rest can pay: an outage, so tell them to try again later.

Collapsing `unavailable` into `unpayable` tells customers their plan is
too cheap during an outage. `CryptoProvider.payable_currencies` also
raises `PaymentProviderNotConfiguredError` up front on a blank API key,
because the per-coin lookups would otherwise record a missing key as
`unknown` and surface an outage message instead of "coming soon".

## Invoices are locked to one coin

`create_invoice` passes `pay_currency`, so the hosted page cannot offer a
coin whose minimum exceeds the price. A minimum can still move inside the
cache window: NOWPayments then returns a 400 whose body mentions "min",
which `nowpayments.create_invoice` raises as `PaymentBelowMinimumError`
rather than a generic error. Callers recover by calling
`minimums.invalidate(code)` and re-rendering the chooser. Never let that
exception reach the buyer as a dead end.

## Rules that predate this feature and still hold

- A blank key raises `PaymentProviderNotConfiguredError`, never a raw API
  failure, so the bot runs with crypto visibly unavailable.
- `create_crypto_payment` commits the `Payment` row BEFORE calling the
  provider, because `order_id` must be a real, permanent local id. A
  failed invoice leaves a harmless orphan pending row.
- The IPN handler verifies the HMAC-SHA512 signature over a sorted-keys
  JSON re-encoding of the body before touching the database, and is
  idempotent on `payment.status == "pending"`.
- Do not add a second path into invoice creation, IBSng, or account
  creation. `create_crypto_payment` and `create_vpn_user` are each the
  single path.

## Admin diagnostics

Settings → 💱 Crypto Minimums shows each coin's cached minimum, its age,
whether it is fresh/stale/unknown, and the last NOWPayments error, with a
force-refresh button. Use it when a buyer reports a missing coin before
assuming a code bug.
