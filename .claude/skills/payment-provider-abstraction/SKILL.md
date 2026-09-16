---
name: payment-provider-abstraction
description: Homeland's PLANNED PaymentProvider interface for Stripe/crypto (create_invoice/verify_webhook/on_payment_confirmed) - NOT YET IMPLEMENTED. Use when building the payment foundation, app/services/payments/*, app/webhook.py, or any Buy/Renew flow that will eventually charge money.
---

# Payment Provider Abstraction (Homeland) - PLANNED, NOT YET BUILT

**Status check first:** as of this writing, `app/services/payments/`,
`app/webhook.py`, and the `PaymentProvider` class described below **do not
exist in this codebase**. Grep before trusting this skill's freshness:

```bash
grep -rn "class PaymentProvider" app/
```

If that now returns a hit, the abstraction has been built - read the real
code instead of this skill, and update or delete this file. Until then,
everything below is the **approved design**, not working code, sourced
from `docs/superpowers/specs/2026-09-14-homeland-bot-design.md` §6. It
exists so the interface gets built consistently whenever it does land,
without re-deriving the design from scratch or re-explaining it in a
fresh session.

Why it's not built yet: the project's own standing instruction is to
implement every other feature first and postpone the payment foundation
until real Stripe/crypto API keys and gateway details are provided. Do
not start implementing `app/services/payments/` unless the user has
explicitly said the keys/details are now available.

## The interface (spec §6)

```python
# app/services/payments/base.py
class PaymentProvider(ABC):
    @abstractmethod
    async def create_invoice(self, *, order_id: str, amount_usd: Decimal, description: str) -> str:
        """Returns a URL (or client secret) to hand the buyer."""

    @abstractmethod
    async def verify_webhook(self, request: web.Request) -> WebhookEvent | None:
        """Verifies signature, parses the callback. None if invalid/irrelevant."""

    @abstractmethod
    async def on_payment_confirmed(self, event: WebhookEvent) -> None:
        """Creates/renews the VPN user and marks the Payment approved - one
        unified path, since Homeland has no manual admin-approval branch."""
```

- Two implementations planned: `app/services/payments/stripe_provider.py`
  and `crypto_provider.py`.
- `on_payment_confirmed` is meant to call the same account-creation path
  every other flow uses - `app/services/vpn_users.py`'s `create_vpn_user`
  (see the `ibsng-xmlrpc-integration` skill for that function's
  pre-check-before-external-call ordering, which a payment-confirmation
  handler must follow too: verify the Payment row's local state before
  ever touching IBSng, since a replayed webhook is exactly the kind of
  duplicate-call scenario that pattern exists to guard against).

## Config placeholders that already exist (in `app/config.py`)

These are real, already in the codebase, blank by default:

```python
stripe_api_key: str = ""
stripe_webhook_secret: str = ""
crypto_gateway_api_key: str = ""
crypto_gateway_ipn_secret: str = ""
crypto_gateway_ipn_callback_url: str = ""
```

Per spec: calling `create_invoice` while a provider's key is blank must
raise a clear `PaymentProviderNotConfiguredError` - not a confusing raw
API failure - so the bot can run today with payment methods visibly
"coming soon" in the UI until real keys are added.

## Webhook routing (planned)

`app/webhook.py` is meant to generalize into one route per registered
provider - `/webhooks/stripe`, `/webhooks/crypto` - each provider
verifying its own signature before touching the DB at all.

## Reference implementation pattern (sibling project, NOT Homeland)

The sibling project `/Users/peyman/telegram-bot` (AloBot - same author,
same IBSng backend, but sells VPN in the opposite direction, priced in
Toman, to customers inside Iran) already has a working hosted-invoice
payment integration at `app/services/nowpayments.py`. It's the closest
confirmed reference for the "hosted invoice + signed IPN webhook" shape
`crypto_provider.py` is meant to follow - **but it is not a drop-in
match**:

- AloBot's gateway is NowPayments (crypto only); Homeland's crypto
  gateway is unspecified/TBD - same *pattern*, different *provider*, so
  don't assume the exact API calls transfer.
- AloBot has no Stripe integration at all - Stripe is Homeland-only.
- AloBot's flow includes a manual admin-approval branch
  (`approve_payment_by_id`) that Homeland's spec explicitly says NOT to
  replicate - `on_payment_confirmed` unifies what AloBot splits across a
  webhook handler and an admin-approval command into one path.

The pattern worth copying from `nowpayments.py`: hosted-invoice creation
via a simple POST returning a `invoice_url`, and HMAC-based IPN signature
verification with a canonical (sorted-keys) JSON re-encoding of the
payload before computing the HMAC - see that file's `verify_ipn_signature`
for the exact technique, since IPN/webhook signature verification is
easy to get subtly wrong (e.g. verifying against the wrong byte
representation of the payload).

## When this skill is actually needed

Only once the user provides real Stripe/crypto credentials and asks to
build the Buy/Renew/payment flow. At that point: brainstorm and spec the
concrete implementation (this skill is not a substitute for that process
for a feature this size), using the interface above as the starting
contract, and update this skill's status section once real code exists.
