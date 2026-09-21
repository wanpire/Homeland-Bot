---
name: payment-provider-abstraction
description: Homeland's implemented PaymentProvider abstraction - CryptoProvider over Plisio, the GET-only API and single secret key, HMAC-SHA1 callback verification with verify_hash inside the body, the invoice status map, and why this codebase deliberately has no per-coin minimum check. Use when touching app/services/payments/*, app/webhook.py, or any Buy/Renew step that charges money.
---

# Payment Provider Abstraction (Homeland)

This is **built and live on Plisio**. NOWPayments was removed on
2026-09-22. Read the real code first:
`app/services/payments/{base,crypto_provider,plisio,service}.py` and
`app/webhook.py`. This skill records the rules that are easy to break and
expensive to get wrong. Design:
`docs/superpowers/specs/2026-09-22-plisio-migration-design.md`.

## The interface (`app/services/payments/base.py`)

```python
class PaymentProvider(ABC):
    async def create_invoice(self, *, order_id, amount_usd, description) -> tuple[str, str]
    def verify_webhook(self, raw_body: bytes, signature: str) -> WebhookEvent | None
```

Two methods, deliberately. A provider talks to its gateway; it never
performs Homeland domain logic (no IBSng calls, no account creation).
Confirming a payment lives in `service.activate_finished_payment`, called
only from the webhook route - see the 2026-09-16 spec §4 for why
`on_payment_confirmed` is deliberately NOT a provider method.

`verify_webhook` keeps its `signature` parameter for interface
compatibility and ignores it: Plisio has no signature header.

## Plisio's API shape

- **GET only.** `GET https://api.plisio.net/api/v1/<action>?api_key=<SECRET_KEY>`.
- **Envelope.** `{"status": "success"|"error", "data": ...}`. A failure
  can arrive with **HTTP 200 and `status: "error"`**, so never trust the
  status code alone - `plisio._get` checks the body.
- **One secret.** The same key authenticates API calls and signs
  callbacks. There is no separate IPN secret.
- **Invoices.** `invoices/new` with `source_currency=USD`,
  `source_amount`, `order_number` (our `Payment.id`, unique per order),
  `order_name`, `callback_url`, `allowed_psys_cids`. The response gives
  `txn_id` and `invoice_url`.
- **Currency IDs** are Plisio's own: `LTC`, `TON`, `USDT_TON`,
  `USDT_TRX`, `TRX`. Never invent codes; check Plisio's Supported
  cryptocurrencies table.

## Callback verification (the part most easily got wrong)

Plisio signs with **HMAC-SHA1**, not SHA512, keyed with the same secret,
over the payload with `verify_hash` removed. The hash travels **inside
the body**, not in a header.

`PLISIO_CALLBACK_URL` **must end in `?json=true`**. Without it Plisio
sends a PHP-serialized form post whose hash this app cannot reproduce,
and every callback would be rejected - meaning customers pay and never
receive their service.

Plisio's own PHP and Node examples disagree on key order (PHP `ksort`s,
Node does not), so `plisio.verify_callback` accepts either the received
key order or the sorted one. Both are HMAC under the secret, so this
concedes nothing to an attacker while avoiding silent rejection of real
callbacks. Comparison uses `hmac.compare_digest`.

## No per-coin minimum check belongs in this codebase

Plisio exposes `min_sum_in` per coin, but it does **not** create the dead
end NOWPayments did. `allowed_psys_cids` offers every accepted coin and
the buyer picks - and switches - on Plisio's own invoice page, which
shows each coin's requirements. So there is no minimum cache, no
payability report, and no in-bot coin chooser. Do not reintroduce one;
the deleted NOWPayments-era design survives in
`docs/superpowers/specs/2026-09-21-crypto-payability-design.md` purely as
a record of why it once existed.

`min_sum_in` is surfaced read-only on the admin Crypto Coins screen
(`adm:settings:coins`) for diagnosis.

## Invoice status map (`app/webhook.py`)

| Plisio status | Homeland `Payment.status` |
|---|---|
| `completed` | `paid` - activates and notifies |
| `expired` with a received amount | `partially_paid` - top-up message |
| `expired` with none | `failed` |
| `cancelled`, `error` | `failed` |
| `new`, `pending`, `pending internal` | unchanged, logged only |
| `cancelled duplicate` | unchanged, logged only |

**`cancelled duplicate` must never fail a payment.** Plisio sets it on
the invoice a buyer abandoned when switching coins; the replacement
invoice, same `order_number` and a new `txn_id`, is the one that
completes. Because of that switch the route refreshes
`Payment.provider_payment_id` to the newest `txn_id` beside the audit
row, before the progress-status early return - a switch usually shows up
on a progress callback, so doing it later would miss the case entirely.

## Rules that predate this migration and still hold

- A blank key raises `PaymentProviderNotConfiguredError`, never a raw API
  failure, so the bot runs with crypto visibly unavailable.
- `create_crypto_payment` commits the `Payment` row BEFORE calling the
  provider, because `order_number` must be a real, permanent local id. A
  failed invoice leaves a harmless orphan pending row.
- The callback route verifies before touching the database, guards
  `order_number` against the int32 range, writes a `PaymentStatusEvent`
  per callback, and is idempotent under a fresh row lock.
- A 500 response is how the route asks Plisio to retry; a permanent
  failure must answer 200 or Plisio retries forever.
- Do not add a second path into invoice creation, IBSng, or account
  creation. `create_crypto_payment` and `create_vpn_user` are each the
  single path.

## Operational notes

Plisio's docs require the calling server's IP to be registered under API
settings (Request IP), and the account needs a wallet for each coin in
`PLISIO_PAY_CURRENCIES`. A coin missing from the invoice page is usually
one of those two, not a code bug - check the Crypto Coins screen first.
