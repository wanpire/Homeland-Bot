# Crypto Payability (per-coin minimum check) — Design Spec

> **Superseded 2026-09-22** by `2026-09-22-plisio-migration-design.md`.
> Kept for the record of why the NOWPayments design looked like this.

Date: 2026-09-21
Status: approved (design reviewed in chat)
Parent spec: `docs/superpowers/specs/2026-09-16-crypto-payment-design.md`
(§6 NOWPayments client, §7 PaymentProvider, §10 Buy flow).

## 1. Summary

NOWPayments enforces a per-coin minimum payment amount that moves with
network fees and prices. Several Homeland plans (roughly $3–$12) sit
near or below those minimums for some accepted coins, and the current
coin-agnostic hosted invoice lets a customer pick a coin whose minimum
exceeds the price and dead-end on the NOWPayments page. The existing
`check_minimum_amount` only blocks when *every* coin is too low.

This spec replaces that with a **per-coin payability check** driven by
NOWPayments' own `GET /v1/min-amount`, cached in Redis, and an **in-bot
coin chooser** that shows only the coins currently payable for that
exact amount. The invoice is then created with `pay_currency` locked,
so the hosted page can no longer dead-end. Buy and Renew both use it.

Out of scope, unchanged: IPN handler (`app/webhook.py`), partial-payment
handling, `Payment` model/migrations, IBSng paths, account creation.

## 2. NOWPayments facts this design relies on

From the official Postman collection (`documenter.getpostman.com/view/7907941/2s93JusNJt`):

- `GET /v1/min-amount?currency_from=<coin>&fiat_equivalent=usd` returns
  `{"currency_from", "currency_to", "min_amount", "fiat_equivalent"}`.
  `fiat_equivalent` is the USD figure (confirmed live 2026-09-18);
  `min_amount` is in the coin's own units. The docs claim that when
  `currency_to` is omitted, NOWPayments "will calculate the minimum
  payment amount for currency_from and currency which you have specified
  as the outcome in the Payment Settings".

  **Live testing on 2026-09-21 disproved that.** Omitted, the response
  carries `currency_to: "false"` and prices each coin against itself:

  | coin | currency_to omitted | currency_to=usdttrc20 |
  |---|---|---|
  | usdttrc20 | $11.71 | $11.71 |
  | usdtbsc | $12.44 | $12.44 |
  | trx | **$0.25** | **$12.31** |
  | ltc | $12.31 | $12.31 |

  TRX is the coin that exposes it: omitted, we would have believed a $5
  plan was payable in TRX and sent the buyer to an invoice they could not
  pay — the exact dead end this feature removes. The client therefore
  ALWAYS sends `currency_to`, set to `Settings.nowpayments_settlement_currency`
  (default `usdttrc20`, the dashboard's payout wallet).
- `POST /v1/invoice` accepts optional `pay_currency`; "If not specified,
  can be chosen on the invoice_url". With it set, the hosted page is
  locked to that coin — verified live 2026-09-21: the response echoed
  `"pay_currency": "TRX"`.
- **Invoice creation does NOT enforce the minimum.** Verified live
  2026-09-21: `POST /v1/invoice` returned 200 for `price_amount: "3.00"`
  locked to TRX, whose minimum is $12.31. The buyer would only discover
  the problem on the hosted page. So the payability pre-check is not one
  safety net among several — it is the only one, which is why its cache
  freshness window is kept short (10 minutes) and why the below-minimum
  error mapping in the client is documented as defensive rather than
  relied upon.
- **No rate limit is published** anywhere in the collection or the help
  center (which only says throttled accounts should contact support).
  The cache below therefore bounds calls to at most one per coin per
  freshness window regardless of traffic.

## 3. Config (`app/config.py`)

```python
# Coins a customer may pay with, as NOWPayments currency codes, in the
# order the chooser lists them. Each must also be enabled in the
# NOWPayments dashboard's coin settings. Extend here (e.g. ",ton") -
# never hardcode a per-coin minimum anywhere; minimums come live from
# GET /v1/min-amount.
nowpayments_pay_currencies: str = "usdttrc20,usdtbsc,trx,ltc"

# The coin the payout wallet settles in; sent as min-amount's currency_to.
nowpayments_settlement_currency: str = "usdttrc20"

@property
def nowpayments_pay_currency_list(self) -> list[str]:
    return [c.strip().lower() for c in self.nowpayments_pay_currencies.split(",") if c.strip()]
```

## 4. Currency registry (`app/services/payments/currencies.py`, new)

```python
@dataclass(frozen=True)
class PayCurrency:
    code: str    # NOWPayments code, e.g. "usdttrc20"
    label: str   # customer-facing, a proper noun - not translated

_LABELS: dict[str, str] = {
    "usdttrc20": "USDT (TRC-20)",
    "usdtbsc": "USDT (BEP-20)",
    "trx": "TRX (Tron)",
    "ltc": "LTC (Litecoin)",
    "ton": "TON",
    "usdtton": "USDT (TON)",
}

def accepted_currencies() -> list[PayCurrency]:
    """Settings order; unknown codes get label=code.upper() so a new coin
    works from .env alone."""

def find_currency(code: str) -> PayCurrency | None
```

## 5. Minimum lookup + Redis cache (`app/services/payments/minimums.py`, new)

```python
FRESH_SECONDS = 10 * 60      # serve without calling NOWPayments
STALE_SECONDS = 6 * 60 * 60  # keep a stale value this long as a fallback
_KEY = "homeland:npmin:{code}"   # JSON {"min_usd": "12.08", "fetched_at": <unix>}
_ERR_KEY = "homeland:npmin:err:{code}"  # last error text, TTL STALE_SECONDS

@dataclass
class CurrencyMinimum:
    currency: PayCurrency
    min_usd: Decimal | None      # None = unknown (no fresh or stale value)
    fetched_at: float | None
    state: str                   # "fresh" | "stale" | "unknown"
    last_error: str | None

async def get_minimums(*, force_refresh: bool = False) -> list[CurrencyMinimum]
async def invalidate(code: str) -> None
```

Algorithm of `get_minimums`:
1. Read every coin's cache entry from Redis (`get_redis()`, one MGET).
2. Coins with an entry younger than `FRESH_SECONDS` (and not
   `force_refresh`) are returned as `fresh` without any API call.
3. The rest are fetched in parallel with `asyncio.gather` via
   `nowpayments.get_min_amount(currency_from=code)`. Success → write the
   entry with TTL `STALE_SECONDS`, delete the error key, return `fresh`.
4. Failure (`NowPaymentsError`, includes 4xx/5xx/timeouts) →
   `logger.error("NOWPayments min-amount lookup failed for %s: %s", code, exc)`,
   store the error text in the error key, then: stale entry exists →
   `logger.warning("Using stale minimum for %s (age %ds)")`, return
   `stale`; else return `unknown` with `min_usd=None`.
5. Redis itself failing (`redis.RedisError`) is logged at error and
   treated as "no cache": every coin is fetched live, results are not
   stored. The purchase flow never crashes on a cache outage.

Bound: at most `len(accepted_currencies())` API calls per
`FRESH_SECONDS`, shared by every user of the bot. No stampede lock —
two simultaneous misses cost one duplicate call, acceptable.

## 6. Payability report and provider contract

`app/services/payments/base.py`:

```python
@dataclass
class PayabilityReport:
    payable: list[PayCurrency]
    too_low: list[tuple[PayCurrency, Decimal]]   # (coin, min_usd)
    unknown: list[PayCurrency]

    @property
    def status(self) -> str:
        # "payable" | "unpayable" (nothing payable, nothing unknown)
        # | "unavailable" (nothing payable, at least one unknown)

    @property
    def lowest_minimum(self) -> Decimal | None   # min over too_low, for the message

class PaymentProvider(ABC):
    @abstractmethod
    async def payable_currencies(self, amount_usd: Decimal) -> PayabilityReport: ...
    @abstractmethod
    async def create_invoice(self, *, order_id: str, amount_usd: Decimal, description: str,
                             pay_currency: str | None = None) -> tuple[str, str]: ...
    @abstractmethod
    def verify_webhook(self, raw_body: bytes, signature: str) -> WebhookEvent | None: ...
```

A coin is payable when `amount_usd >= min_usd` (fresh or stale).

`CryptoProvider.payable_currencies` builds the report from
`get_minimums()`. `CryptoProvider.create_invoice` forwards
`pay_currency`.

`app/services/payments/nowpayments.py`:
- `get_min_amount(*, currency_from)` — always sends `currency_to`, set
  to `Settings.nowpayments_settlement_currency` (§2).
- `create_invoice(..., pay_currency: str | None = None)` adds
  `"pay_currency"` to the payload when given. The internal
  `check_minimum_amount` call and the function itself are **removed**
  (the chooser already guaranteed payability from the same data).
- A 400 response whose body text contains `"min"` (case-insensitive;
  covers "minimal"/"minimum"/"AMOUNT_MINIMAL_ERROR") raises
  `PaymentBelowMinimumError` instead of `NowPaymentsError`, so drift
  inside the freshness window is recoverable. **Verify the real body
  live** (§10) and tighten the match if NOWPayments uses a code.

`app/services/payments/service.py`:
- `quote_amount(session, plan) -> tuple[Decimal, DiscountCode | None]`
  extracted from `create_crypto_payment` so the chooser and the invoice
  price come from one computation.
- `create_crypto_payment(..., pay_currency: str)` — required keyword,
  forwarded to the provider.
- `check_payability(amount_usd) -> PayabilityReport` — thin wrapper on
  `_provider.payable_currencies` so handlers never import the provider.

## 7. Bot flow

Callback data (both flows keep their existing prefixes):

| data | screen |
|---|---|
| `buy:confirm:<plan_id>` (existing) | now: chooser / unpayable / unavailable |
| `buy:pay:<plan_id>:<code>` (new) | create invoice locked to `<code>` → payment link |
| `renew:confirm:<vu>:<plan_id>` (existing) | same as buy |
| `renew:pay:<vu>:<plan_id>:<code>` (new) | same as buy |

`buy_confirm_cb` / `renew_confirm_cb`:
1. Load plan (existing guards), `amount, _ = await quote_amount(...)`.
2. `PaymentProviderNotConfiguredError` → existing coming-soon text.
3. `report = await check_payability(amount)`:
   - `payable` → `t("choose_pay_currency", lang, price=...)` with
     `pay_currency_keyboard(prefix, report.payable, back_cb, lang)`:
     one button per payable coin labelled `coin.label`, then Back to the
     price summary (`buy:plan:<id>` / `renew:plan:<vu>:<id>`).
   - `unpayable` → `t("payment_below_minimum", lang, min=format_price_usd(report.lowest_minimum))`
     (reworded to name the minimum and suggest a higher plan or support)
     with Back to the plan list (`buy:category:<cat>` /
     `renew:category:<vu>:<cat>`) and Back to Menu.
   - `unavailable` → existing `payment_unavailable`, Back to Menu.

`buy_pay_cb` / `renew_pay_cb`:
1. Parse and validate `<code>` with `find_currency`; unknown → re-run
   the confirm screen (stale keyboard).
2. `report = await check_payability(amount)`; if the coin is not in
   `report.payable` → chooser again with `t("payment_currency_changed")`
   prepended (or the unpayable/unavailable screen if nothing is left).
3. `create_crypto_payment(..., pay_currency=code)`:
   - `PaymentBelowMinimumError` → `await invalidate(code)`, then step 2's
     re-render (NOWPayments disagreed with our cache: refetch next time).
   - `NowPaymentsError` → log + `payment_unavailable`.
   - success → existing `payment_link_heading` + link keyboard.

Handlers stay thin: the shared rendering lives in one helper module
`app/bot/handlers/_payability.py` (`render_payability(callback, report,
lang, *, chooser_prefix, back_to_summary_cb, back_to_plans_cb, notice=None)`)
used by both routers.

## 8. i18n (`app/i18n/texts.py`, fa + en)

- `choose_pay_currency`: "💱 <b>Choose a coin</b>\n\nPrice: {price}\nPick the coin you'll pay with — only coins that currently accept this amount are shown:"
- `payment_below_minimum` (reworded): "⚠️ This plan's price is below the network minimum for every coin we accept right now (lowest minimum: {min}). Please choose a higher-priced plan, or contact support."
- `payment_currency_changed`: "⚠️ That coin's minimum just changed and no longer accepts this amount. Please pick another coin."
- `back_to_plans_button`: "⬅️ Back to Plans"

## 9. Admin diagnostics (`adm:settings:minimums`)

Settings menu gains "💱 Crypto Minimums". The screen (English only)
lists each accepted coin: `USDT (TRC-20): $12.08 — fresh, 3 min ago`,
or `stale, 2 h ago — last error: 502 ...`, or `unknown — last error: ...`.
Buttons: "🔄 Refresh now" (`adm:settings:minimums:refresh`, calls
`get_minimums(force_refresh=True)`), "⬅️ Back to Settings". Full-admin
only, mirroring the other settings screens.

## 10. Live verification (after the new key/secret are in `.env`)

1. Admin → Settings → Crypto Minimums → Refresh: all four coins fresh
   with plausible USD minimums (~$10–15 range as of 2026-09-18).
2. Done 2026-09-21: `currency_to` must be sent explicitly (see §2).
   `nowpayments_settlement_currency` carries it, so a dashboard payout
   change is a config change, not a code change.
3. Buy a $5 plan: chooser shows only coins whose minimum ≤ $5 (likely
   none today → unpayable message). Buy a $12+ plan: chooser lists the
   payable coins; open the link and confirm the NOWPayments page is
   locked to the chosen coin.
4. Force a below-minimum locked invoice from a scratch script (no key in
   the repo or logs) to capture the exact 400 body and tighten §6's
   matcher if needed.

## 11. Tests (`make test`)

- `tests/unit/test_currencies.py`: settings order, unknown code label,
  `find_currency`.
- `tests/functional/test_minimums.py` (real Redis from the test stack,
  `httpx.AsyncClient.get` monkeypatched as in `test_nowpayments_client.py`):
  fresh fetch stores and returns; second call within window makes zero
  HTTP calls; error with stale → stale; error without stale → unknown +
  error key; `force_refresh` bypasses; `invalidate` drops the key.
- `tests/functional/test_payability.py`: report status for fully
  payable / partially payable / fully unpayable / unavailable;
  `lowest_minimum`.
- `tests/functional/test_buy_flow.py` + `test_renew_flow.py`: confirm →
  chooser lists exactly the payable coins (partial case); unpayable
  message names the minimum; unavailable message; `buy:pay` creates the
  invoice with `pay_currency` and shows the link; invoice-time
  `PaymentBelowMinimumError` re-shows the chooser with the notice;
  Back buttons present.
- `tests/functional/test_nowpayments_client.py`: `pay_currency` in
  payload; min-amount request omits `currency_to`; 400-with-"min" →
  `PaymentBelowMinimumError`; old `check_minimum_amount` tests removed.
- `tests/functional/test_admin_settings.py`: minimums screen renders
  states; refresh forces a fetch; non-full admin blocked.
