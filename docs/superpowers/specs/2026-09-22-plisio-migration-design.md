# Plisio Migration (replacing NOWPayments) — Design Spec

Date: 2026-09-22
Status: approved (design reviewed in chat)
Supersedes: `docs/superpowers/specs/2026-09-16-crypto-payment-design.md` §6
(NOWPayments client) and, in full,
`docs/superpowers/specs/2026-09-21-crypto-payability-design.md` — that
whole feature exists to work around a NOWPayments-specific dead end that
Plisio does not have (§4 below).

## 1. Summary

Homeland drops NOWPayments and takes crypto payments through Plisio.
`CryptoProvider` keeps its place behind `PaymentProvider`; everything
underneath it is replaced. The per-coin minimum machinery built on
2026-09-21 is deleted rather than ported, because Plisio lets the buyer
choose and switch coins on its own invoice page, so a coin whose minimum
is too high is never a dead end.

Unchanged: `PaymentProvider` itself, the plan/pricing model, `Payment`
and `PaymentStatusEvent` (including the raw-status audit trail), the
webhook's locking and idempotency, the single account-creation path
(`create_vpn_user`), the aiohttp server, its port, and the
`/webhooks/crypto` route.

## 2. Plisio API facts this design relies on

From <https://plisio.net/documentation> (Create an invoice, Crypto coins,
Supported cryptocurrencies, Manage invoice updates).

- **Transport.** Every call is `GET https://api.plisio.net/api/v1/<action>`
  with `api_key=<SECRET_KEY>` as a query parameter. Responses are JSON,
  shaped `{"status": "success"|"error", "data": {...}}`. Errors carry
  `data.name`, `data.message`, `data.code` with HTTP 400/401/422/500.
- **One secret.** The same `SECRET_KEY` authenticates API calls *and*
  signs callbacks. There is no second IPN secret, so
  `NOWPAYMENTS_IPN_SECRET` has no successor.
- **Invoice creation.** `GET /invoices/new` with `source_currency=USD`,
  `source_amount`, `order_number` (must be unique per store order),
  `order_name`, `callback_url`, `allowed_psys_cids`, `api_key`. Response
  `data.txn_id` (Plisio's id) and `data.invoice_url` (the page to hand
  the buyer). `currency` is optional: left unset, the buyer picks among
  the coins named in `allowed_psys_cids`.
- **Switching coins is normal.** "When a user changes the currency, a new
  invoice (new_id) is created. After it is paid, the system automatically
  moves all related invoices to the cancelled duplicate status to prevent
  payment duplication."
- **Currency IDs** (the ID column of Supported cryptocurrencies), for the
  five wallets on this account: `LTC` (Litecoin), `TON` (Toncoin),
  `USDT_TON` (Tether TON), `USDT_TRX` (Tether TRC-20), `TRX` (Tron).
- **Coin list.** `GET /currencies/USD` returns, per coin: `cid`, `name`,
  `rate_usd`, `price_usd`, `precision`, `min_sum_in`, `hidden` (whether
  it is selected in store settings) and `maintenance`.
- **Request IP.** The docs note that API calls need the calling server's
  IP registered under API settings. This is a dashboard action, recorded
  in §9.

## 3. Callback verification (the part that is easy to get wrong)

Plisio does **not** use NOWPayments' HMAC-SHA512-over-sorted-JSON scheme.
It POSTs the invoice update to `callback_url` with a `verify_hash` field,
computed as **HMAC-SHA1 keyed with the same `SECRET_KEY`** over a
serialization of the payload with `verify_hash` removed.

The docs give two serializations:

- **PHP form post:** `ksort($post)` then PHP `serialize($post)`.
- **JSON:** required for non-PHP integrations, and enabled by appending
  `json=true` to the callback URL. The documented Node example spreads
  the parsed object, deletes `verify_hash`, and hashes
  `JSON.stringify(ordered)` — i.e. compact JSON in the payload's own key
  order, not sorted.

Homeland therefore registers `…/webhooks/crypto?json=true` and verifies
the JSON variant. Because the two documented examples disagree about key
order, `verify_callback` accepts **either** candidate:

1. compact JSON (`separators=(",", ":")`, `ensure_ascii=False`) in the
   received key order — the documented Node behaviour;
2. the same with keys sorted — matching the PHP example's `ksort`.

Both are HMAC-SHA1 under the secret, so accepting either costs no
security (an attacker still needs the key) and avoids silently rejecting
genuine callbacks, which would mean a paying customer never gets their
service. The matched variant is logged at debug so the live behaviour is
observable. Comparison uses `hmac.compare_digest`.

Values arrive as JSON strings or numbers; re-encoding preserves them
because Python's `json` round-trips both, and `ensure_ascii=False`
matches `JSON.stringify` for non-ASCII.

## 4. No per-coin minimum check (deleting, not porting)

NOWPayments locked one coin per invoice, so a coin whose minimum exceeded
the price stranded the buyer on the hosted page. Plisio's model removes
the premise: `allowed_psys_cids` offers all five coins and the buyer can
switch on Plisio's page, which shows each coin's own requirements.

So the following are **deleted**: `app/services/payments/minimums.py`,
`app/services/payments/currencies.py`'s payability role,
`PayabilityReport`, `payable_currencies`, `check_payability`, the
`buy:pay:*` / `renew:pay:*` chooser handlers,
`app/bot/handlers/_payability.py`, `app/bot/keyboards/payability.py`,
the Redis cache keys, `NOWPAYMENTS_SETTLEMENT_CURRENCY`, and the
i18n keys `choose_pay_currency`, `payment_currency_changed`,
`payment_below_minimum`, `back_to_plans_button`.

"Pay with Crypto" returns to creating the invoice directly and showing
the link — the shape the flow had before 2026-09-21.

`min_sum_in` is still surfaced read-only in the admin Crypto Coins screen
(§7) and checked live during verification (§9); if a coin's minimum ever
turns out to exceed a live plan price, the buyer simply picks another
coin, and the screen shows why.

## 5. Config (`app/config.py`)

Removed: `nowpayments_api_key`, `nowpayments_ipn_secret`,
`nowpayments_ipn_callback_url`, `nowpayments_pay_currencies`,
`nowpayments_settlement_currency`.

Added:

```python
# Plisio - one secret key authenticates API calls AND signs callbacks
# (there is no separate IPN secret). create_crypto_payment raises
# PaymentProviderNotConfiguredError while this is blank, so the bot runs
# with crypto visibly unavailable until a key is provisioned.
plisio_secret_key: str = ""

# Full public URL Plisio POSTs invoice updates to. MUST carry
# ?json=true: without it Plisio sends a PHP-serialized form post whose
# verify_hash this app cannot check (see spec §3).
plisio_callback_url: str = ""

# Coins the buyer may pay with, as Plisio currency IDs (the ID column of
# Supported cryptocurrencies), sent as allowed_psys_cids. Each must also
# have a wallet configured on the Plisio account.
plisio_pay_currencies: str = "LTC,TON,USDT_TON,USDT_TRX,TRX"

@property
def plisio_pay_currency_list(self) -> list[str]:
    return [c.strip().upper() for c in self.plisio_pay_currencies.split(",") if c.strip()]
```

`bot_username` stays: it still builds the return-to-bot links, now passed
as `success_invoice_url` / `fail_invoice_url`.

## 6. Client and provider

`app/services/payments/plisio.py` (replaces `nowpayments.py`):

```python
PlisioError(Exception)                       # API/transport failure
PaymentProviderNotConfiguredError(Exception) # blank secret key

async def create_invoice(*, order_id: str, amount: Decimal, description: str) -> tuple[str, str]
    # GET /invoices/new with source_currency=USD, source_amount=amount,
    # order_number=order_id, order_name=description,
    # allowed_psys_cids=<settings list>, callback_url=<settings>,
    # success_invoice_url/fail_invoice_url=https://t.me/<bot_username>
    # when set. Returns (invoice_url, txn_id). Raises PlisioError when
    # status != "success" or either field is missing.

async def list_currencies() -> list[dict[str, Any]]
    # GET /currencies/USD -> data list, for the admin Crypto Coins screen.

def verify_callback(raw_body: bytes) -> dict[str, Any] | None
    # Parses JSON, checks verify_hash per §3, returns the payload or None.
```

`CryptoProvider` keeps two methods:

```python
async def create_invoice(self, *, order_id, amount_usd, description) -> tuple[str, str]
def verify_webhook(self, raw_body: bytes, signature: str) -> WebhookEvent | None
```

`verify_webhook` keeps its signature for compatibility with the webhook
route and the abstraction, but ignores `signature`: Plisio carries the
hash inside the body, not in a header. That is documented in the
docstring. It maps the payload onto `WebhookEvent(provider_payment_id=
txn_id, order_id=order_number, raw_status=status, paid_amount=amount)`.

`PaymentProvider` loses `payable_currencies`; `create_invoice` loses
`pay_currency`. `service.create_crypto_payment` loses its `pay_currency`
argument and `check_payability` disappears. `quote_amount` stays — Buy
and Renew still need the discounted price for display.

`Payment.provider` default becomes `"plisio"`. Existing rows keep
`"nowpayments"`, which is historically accurate; no data migration.

## 7. Status mapping (`app/webhook.py`)

Plisio statuses map onto Homeland's coarse `Payment.status`:

| Plisio status | Homeland | behaviour |
|---|---|---|
| `completed` | `paid` | activate, notify |
| `expired` + `amount` > 0 | `partially_paid` | top-up message, stays open |
| `expired` + no amount | `failed` | failure message |
| `cancelled`, `error` | `failed` | failure message |
| `new`, `pending`, `pending internal` | — | logged only |
| `cancelled duplicate`, `mismatch` | — | logged only, never fails a payment |

`cancelled duplicate` must never mark a payment failed: it is what Plisio
sets on the abandoned invoice when a buyer switches coins, and the
replacement invoice is the one that completes. Because a switch creates a
*new* Plisio invoice while `order_number` stays ours, `provider_payment_id`
is updated to the latest `txn_id` seen for that payment.

`expired` is Plisio's nearest equivalent to `partially_paid`: the docs say
to "look for the amount field to verify payment. The full amount may not
have been paid." The existing top-up message and keyboard are reused
unchanged.

The route keeps its lock-and-re-fetch idempotency, its int32 `order_id`
guard, the `PaymentStatusEvent` audit row per callback, and its 500-on-
IBSng-error so Plisio retries. Only `_FINAL_STATUSES`, `verify_webhook`'s
inputs, and comments change.

## 8. Admin screens

- **Crypto Settlement Address** stays as an internal reference record and
  no longer validates through any API (Plisio documents no
  address-validation endpoint). Network labels become Plisio's:
  `LTC`, `TON`, `USDT_TON`, `USDT_TRX`, `TRX`.
- **Crypto Minimums** is replaced by **Crypto Coins**
  (`adm:settings:coins`), a read-only screen listing each configured coin
  with its live `price_usd`, `min_sum_in` and, where the account reports
  it, `hidden`/`maintenance` state, plus the equivalent minimum in USD
  (`min_sum_in × price_usd`) so an admin can see at a glance whether a
  coin can take a small plan. Fetched on demand, no cache. English only,
  Back to Settings, full-admin gated like its neighbours.

## 9. Rollout and live verification

1. Ask the user for the Plisio secret key; install it into `.env` on
   bot.alonet.co as `PLISIO_SECRET_KEY` without printing it. Set
   `PLISIO_CALLBACK_URL=https://bot.alonet.co/webhooks/crypto?json=true`.
2. Dashboard actions for the user: register the server IP under API
   settings (Request IP), and confirm the five wallets are enabled.
3. Verify live: `GET /currencies/USD` returns the five coins; check each
   `min_sum_in` against the cheapest active plan and report anything
   surprising. Create one real invoice for a live plan price and confirm
   the page offers exactly those five coins.
4. Confirm the callback path end to end: a forged body is rejected, and a
   body signed with the real secret for a nonexistent order returns
   "ignored" without side effects (the same two probes used for the
   NOWPayments migration).

## 10. Tests (`make test`)

Deleted: `tests/functional/test_nowpayments_client.py`,
`test_payability.py`, `test_minimums.py`, `tests/unit/test_currencies.py`.

Added `tests/functional/test_plisio_client.py`:
- invoice request carries `source_currency=USD`, the amount, our
  `order_number`, `allowed_psys_cids` from settings, the callback URL,
  and the api key;
- success response yields `(invoice_url, txn_id)`;
- `status: "error"` and a malformed/missing-field body raise `PlisioError`;
- a blank key raises `PaymentProviderNotConfiguredError`;
- `verify_callback` accepts a correctly signed payload in received-key
  order, accepts the sorted-key variant, rejects a wrong secret, a
  tampered field, a missing `verify_hash`, and non-JSON.

Updated: `test_webhook.py` for Plisio payloads and each status in §7
(including `cancelled duplicate` not failing a payment, and `expired`
with and without an amount); `test_buy_flow.py` / `test_renew_flow.py`
for the direct-to-invoice flow; `test_payments_service.py`,
`test_admin_settings.py` (Crypto Coins), `test_admin_crypto_settlement.py`
(no validation call), `tests/conftest.py` env, `tests/unit/test_config.py`.

## 11. Docs to update

`CLAUDE.md`, `.env.example`, and
`.claude/skills/payment-provider-abstraction/SKILL.md` (rewritten for
Plisio: the GET/api_key transport, the HMAC-SHA1 `verify_hash` scheme and
the `json=true` requirement, the status table, and the standing rule that
no per-coin minimum machinery belongs in this codebase). The two
superseded specs get a header line pointing here rather than being
deleted, since they record why the old design existed.
