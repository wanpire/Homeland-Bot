# Homeland Bot — Design Spec

Date: 2026-09-14
Status: proposed

## 1. Product summary

Homeland is a Telegram bot that sells "reverse VPN" service — Iran-based IP
addresses — in USD to Iranian customers living outside Iran. It is a
separate project, bootstrapped from the existing AloBot codebase
(`/Users/peyman/telegram-bot`, Python 3.12 / aiogram 3.x / PostgreSQL +
SQLAlchemy 2.0 + Alembic / Redis), which sells the opposite direction of
VPN in Toman to customers inside Iran. Homeland reuses AloBot's proven
architecture and its IBSng integration pattern, but trims its feature set
to a much smaller, English-only, USD product and adds data-quota tracking,
which AloBot has never needed.

Backend accounting/provisioning is IBSng, the same software AloBot
integrates with, running on the same server (confirmed: same IBSng
instance/URL, separate ISP name, credentials, and groups for Homeland).

## 2. Scope

### 2.1 Kept from AloBot (ported/adapted)

- aiogram 3.x router-per-domain structure, registered in `app/main.py`.
- Stack: PostgreSQL + SQLAlchemy 2.0 + Alembic, Redis for FSM state and
  background tasks, pydantic-settings, Docker Compose.
- `app/services/ibsng/client.py` — the XML-RPC `IBSngClient`, including
  every confirmed-against-a-real-server quirk documented in its module
  docstring (owner_name requirement, flat updateUserAttrs shape,
  getUserInfo's attrs-vs-basic_info split, etc.). Extended with a new
  `get_user_data_usage()` method (see §5).
- Auth / blocked-user / private-chat-only / user-tracking middlewares,
  unchanged.
- Discount codes (`discount_code.py`, `discount_code_usage.py`,
  `discounts.py`), broadcast, sales reports — ported and adapted (see
  §7).
- Expiry reminders (`services/reminders.py`) — ported, plus a new
  low-quota reminder (see §8).
- The standing UX rule: every interactive flow/menu includes a "Back"
  (and "Back to Menu" where relevant) button by default.
- `AppConfig` key/value store for admin-editable runtime settings
  (support text, ToS/Privacy content, reminder on/off).

### 2.2 Dropped entirely

- Trial/test service flow (`states/trial.py`, `services/*trial*`, the
  "🎁 سرویس تست" menu button, `set_trial` admin flow) — no free trial
  anywhere in Homeland.
- Resellers (`db/models/reseller.py`, `services/resellers.py`,
  `states/reseller_buy.py`, `states/add_reseller.py`) — not in scope
  yet; may return in a later phase but nothing in this design should
  make adding it back harder.
- `dns_switcher.py` and `dns_admin.py` — AloBot-specific Cloudflare
  datacenter switching for its own outbound VPN targets; irrelevant to
  Homeland.
- Service *categories* (normal/prime/fixed/junior), fixed *locations*
  (`service_location.py`), and the *user_count* dimension — Homeland
  has exactly 4 flat plans, no matrix.
- Card-to-card manual payment, the "✅ تایید" admin-approval button, and
  the auto-approve background review loop (`services/auto_approve.py`)
  — Homeland's only payment methods are Stripe and crypto, both
  webhook-confirmed, no manual admin approval step.
- Persian-digit / RTL / bidi text helpers (`to_persian_digits`,
  `isolate_ltr`) and Toman price formatting — Homeland is English/USD
  only.
- `openvpn_profiles.py`'s category/location-bound `.ovpn` profile
  matrix — replaced by a single OpenVPN Connect tutorial guide (§6).

### 2.3 New for Homeland

- Data-quota tracking end to end (IBSng read, `My Services` display,
  low-quota reminder).
- `PaymentProvider` abstraction with Stripe and crypto implementations
  (both stubbed, no live keys).
- USD price formatting.
- ToS/Privacy delivery (static route + in-bot section).

## 3. Main user menu

Replaces AloBot's menu entirely:

- 🔑 Buy Subscription
- ♻️ Renew Service
- 🛍 My Services (shows remaining data quota, not just expiry)
- 📚 Tutorial & Support (includes Terms & Privacy)

No trial button. Every screen reachable from here keeps a Back /
Back to Menu button, per the standing UX rule.

## 4. Catalog: flat plans, not a matrix

AloBot's `Service` model is a 4-dimensional matrix (category × location ×
duration × user_count) bound to an IBSng `Group`. Homeland has exactly 4
plans and no other axes, so this collapses to one model:

```python
class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[int]
    name: Mapped[str]              # "2 Weeks", "1 Month", "2 Months", "3 Months"
    duration_days: Mapped[int]     # 14, 30, 60, 90
    data_cap_mb: Mapped[int]       # 2048, 5120, 10240, 102400
    price_usd: Mapped[Decimal]     # 2.50, 5.00, 10.00, 30.00
    group_name: Mapped[str]        # bound IBSng group (FK-equivalent, string, matches AloBot's pattern)
    is_active: Mapped[bool]
    sort_order: Mapped[int]
```

Seeded once via an Alembic data migration with the 4 plans below. Admin
can edit price / active state / group binding, but cannot create new
dimensional combinations — there is no plan-matrix editor, just a plan
list.

| Name      | Duration | Data cap | Price  |
|-----------|----------|----------|--------|
| 2 Weeks   | 14 days  | 2 GB     | $2.50  |
| 1 Month   | 30 days  | 5 GB     | $5.00  |
| 2 Months  | 60 days  | 10 GB    | $10.00 |
| 3 Months  | 90 days  | 100 GB   | $30.00 |

`app/services/catalog.py` shrinks to `list_plans` / `get_plan` /
`update_plan` — no category/location/slot-matrix logic, no
`format_plan_title`/Persian-digit helpers. Price formatting is a plain
`f"${price:.2f}"` helper.

## 5. Data quota — the new integration surface

AloBot's plans are confirmed unlimited-volume (its own code comment:
"every plan is unlimited-volume, so quota is a flat, unconditional
line"). Homeland's core "My Services" requirement — remaining data
quota, not just expiry — needs real usage data from IBSng, which
requires the IBSng groups behind Homeland's 4 plans to be configured for
**volume/traffic-based accounting** (credit = data cap), not AloBot's
time-based groups.

**Deployment prerequisite (blocks this feature, not the rest of the
build):** the 4 IBSng groups for Homeland's plans must exist and be
configured for volume-based credit before quota display can show real
numbers. They are not set up yet as of this spec. Build proceeds against
this design; the exact credit unit (bytes / KB / MB — undocumented, like
every other IBSng behavior recorded in `ibsng/client.py`'s module
docstring) will be confirmed against the real server during integration
testing, and `ibsng/client.py`'s docstring will be extended with
whatever is confirmed, matching its existing documentation style.

Design:

- `IBSngClient.get_user_data_usage(user_id)` calls
  `user_balance.getUserBalanceInfoByUserID` (already used for
  `get_user_balances`, just not for quota today) and returns
  `(used_mb, total_mb)` or `None` if unavailable.
- `create_user` assigns IBSng credit equal to the plan's `data_cap_mb`
  at purchase/renewal time, instead of AloBot's hardcoded
  `DEFAULT_CREATE_CREDIT = 10`.
- `VPNUser` gains `data_cap_mb: Mapped[int]` (snapshot of the plan's cap
  at purchase time, so a later plan price/cap edit never retroactively
  changes an existing subscription — mirrors how `Payment.amount`
  already snapshots price) and `low_quota_reminder_sent_at: Mapped[dt.datetime | None]`
  alongside the existing `expiry_reminder_sent_at`.
- `My Services` and the low-quota reminder both read usage live from
  IBSng on each call, exactly like `expires_at` is read live today via
  `get_user_expiry` — no local usage caching.

## 6. Payment abstraction

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
        """Creates/renews the VPN user and marks the Payment approved -
        the same logic AloBot's approve_payment_by_id and webhook handler
        both call, unified into one path since Homeland has no manual
        admin-approval branch."""
```

- `app/services/payments/stripe_provider.py` and `crypto_provider.py`
  implement it. Both read placeholder settings that don't exist yet —
  `stripe_api_key: str = ""`, `stripe_webhook_secret: str = ""`,
  `crypto_gateway_api_key: str = ""`, `crypto_gateway_ipn_secret: str = ""`
  — same "optional, blank until provisioned" pattern AloBot already
  uses for `dns_switcher_base_url`/`nowpayments_api_key`. Calling
  `create_invoice` with a blank key raises a clear
  `PaymentProviderNotConfiguredError` rather than a confusing API
  failure, so the bot can run today with payment methods visibly
  "coming soon" until real keys are added later.
- `app/webhook.py` generalizes AloBot's single-purpose NowPayments
  route into one route per registered provider
  (`/webhooks/stripe`, `/webhooks/crypto`), each provider verifying its
  own signature before touching the DB — same shape as today's
  `_handle_nowpayments_ipn`.
- `crypto_provider.py` follows the same hosted-invoice pattern as
  AloBot's `nowpayments.py` (their existing crypto gateway), since
  that's the closest confirmed reference implementation; the concrete
  crypto gateway can be swapped later without touching the interface.
- No card-to-card path. `Payment.method` becomes `"stripe" | "crypto"`.

## 7. Admin panel

Included:
- **Broadcast** — ported as-is.
- **Discount codes** — ported, scoped to `plan_id: int | None` (null =
  all plans) instead of AloBot's category scope, since Homeland has no
  categories. Percent, usage limit, public/private — unchanged.
- **Sales reports** — ported, grouped by plan instead of category; no
  reseller-commission section.
- **Basic service/user ops** — lookup a user/service, lock, manual
  renew/revoke (admin escape hatch for support cases).
- **Content admin** — editable support text and ToS/Privacy content via
  `AppConfig`, reminder on/off toggle.

Excluded (per your answer): DNS admin, resellers (not yet), the
category/location/group-matrix admin screens (no matrix exists).

## 8. Reminders

`services/reminders.py` ported with two checks per cycle instead of one:
- Expiry reminder (unchanged: 24h-before window, `expiry_reminder_sent_at`
  gates it, cleared on renewal).
- **New** low-quota reminder: fires once per cycle when
  `used_mb / data_cap_mb` crosses a threshold (proposed 90%, admin-
  configurable via `AppConfig` like `reminder_enabled` already is),
  gated by the new `low_quota_reminder_sent_at`, cleared on renewal
  alongside the expiry one. Both reminders push the user toward "Renew
  Service".

## 9. Protocols & tutorials

Only L2TP and OpenVPN are offered — no protocol restriction per plan,
every plan can use either.

`TutorialPlatform` / `TutorialProtocol` / `TutorialGuide` ported as-is
structurally, but with the category/location dimensions dropped (neither
exists in Homeland) — a guide is keyed on `(platform_id, protocol_id)`
only. Seeded content:
- L2TP × {iOS, Android, Windows, macOS} — 4 separate guides.
- OpenVPN × OpenVPN Connect — 1 guide (covers the app across platforms;
  the schema still allows splitting into per-platform OpenVPN guides
  later without a model change, same as AloBot's guide system already
  supports for any platform/protocol pair).

Each purchased service's post-purchase flow shows protocol-specific
setup instructions (mirrors AloBot's `start_post_purchase_setup`).

## 10. Terms of Service / Privacy Policy

Needed for Stripe merchant onboarding, which expects a real URL, not a
Telegram deep link. Delivered two ways from one `AppConfig`-stored
source:
- A static HTML route on the existing aiohttp webhook app —
  `GET /legal/terms`, `GET /legal/privacy` — simple server-rendered
  page, no separate static site.
- A "Terms & Privacy" entry under Tutorial & Support showing the same
  text in-bot.

## 11. Infrastructure isolation

Own Docker Compose project (own project name, own network — no
`dns-switcher-net` dependency), own `Dockerfile`/`requirements.txt`, own
Postgres database and role (`homeland`/`homeland`, separate from
AloBot's `vpnbot`), own Redis **container** (full isolation rather than
sharing AloBot's Redis with a different DB index — simpler to reason
about and avoids any risk of FSM key collisions between the two bots),
own bot token. `IBSNG_BASE_URL` points at the same IBSng server AloBot
uses (confirmed), with Homeland's own `IBSNG_ISP_NAME`, credentials, and
groups — the existing config pattern (`app/config.py`'s `Settings`)
already supports this with zero code changes, just a separate `.env`.

## 12. Repository

Fresh `git init` at `/Users/peyman/Homeland-bot` (this repo) —
independent history, not a clone of `telegram-bot`. Relevant AloBot
files are copied and adapted, not shared via git history or a
subtree/submodule.

## 13. Out of scope for this design (explicitly deferred)

- Real Stripe/crypto API keys and going live with payments — keys are
  provisioned and added separately, per your instruction. Config
  placeholders only.
- Resellers.
- Any admin screen beyond §7.
- CI/CD, GitHub Actions — deploy access and the actual push will follow
  once the initial build is done, per your message.

## 14. Open risks to verify during implementation

- **IBSng credit unit for volume accounting** — unconfirmed until tested
  against the real server with real volume-accounted groups (§5).
- **IBSng group setup** — the 4 Homeland groups don't exist yet; buy/
  renew flows can't be end-to-end tested against real IBSng until they
  do. Development can proceed with the groups mocked/stubbed until then.
