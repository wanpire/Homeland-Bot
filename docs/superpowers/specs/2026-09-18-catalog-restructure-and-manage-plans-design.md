# Catalog Restructure + Manage Plans Design

## 1. Context

Homeland's real IBSng groups changed on the shared instance (confirmed by
listing `IBSngClient.list_groups()` against production on 2026-09-18):

- The old capped-Stream groups (`1M-1U-Iran-30G`, `2M-1U-Iran-60G`,
  `3M-1U-Iran-100G`) **no longer exist**.
- New groups exist in their place: `1M-1U-Iran-Unlimited`,
  `2M-1U-Iran-Unlimited`, `3M-1U-Iran-Unlimited`.
- A new Scroll-tier group exists: `3M-1U-Iran-30G`.
- `2W-1U-Iran-5G` and `Trial-Iran` are unchanged.

Production `plans` table at the same moment (id / name / category / group /
price / real payment count):

| id | name | category | group | price | payments |
|----|------|----------|-------|-------|----------|
| 5 | Trial | trial | Trial-Iran | $0.00 | 0 |
| 6 | 2 Weeks | scroll | 2W-1U-Iran-5G | $3.00 | 1 |
| 7 | 1 Month | scroll | 1M-1U-Iran-10G | $5.00 | 0 |
| 8 | 2 Months | scroll | 2M-1U-Iran-20G | $9.00 | 0 |
| 9 | 1 Month | stream | 1M-1U-Iran-30G | $12.00 | 1 |
| 10 | 2 Months | stream | 2M-1U-Iran-60G | $20.00 | 0 |
| 11 | 3 Months | stream | 3M-1U-Iran-100G | $29.00 | 0 |
| — | — | — | — | — | (11 actually has 1 payment, 10 has 0) |

`Payment.plan_id` and `VPNUser.plan_id` are both FKs to `plans.id`
(`app/db/models/payment.py:36`, `app/db/models/vpn_user.py:30`). Plans 6, 9,
and 11 are referenced by real payment rows, so those rows must never be
deleted — deleting them would break FK integrity on real financial
history. This is why the restructure below updates/deactivates existing
rows rather than replacing the whole catalog the way migration `0004` did
on the pre-launch database.

Two independent pieces of work follow from a conversation with the
product owner:

1. **Catalog restructure** — introduce a new `trip` category, retire the
   old capped-Stream plans in favor of new unlimited-Stream plans, add a
   new Scroll 3-month tier, and represent "Unlimited" data properly in
   both languages.
2. **Manage Plans admin feature** — let an admin edit `price_usd` and
   `is_active` on existing plan rows from inside the bot, instead of
   needing a migration for every price change. This is exactly the
   boundary `app/db/models/plan.py`'s docstring already documents: "Admin
   can edit price/group_name/is_active but never creates a new plan
   through the bot; new plans are a schema/seed change, not an admin
   action." Group name editing is explicitly out of scope for this pass.

These ship as separate, sequential tasks in one plan: the restructure
migration first (data-integrity-sensitive, mechanical), then the admin
feature (new subsystem) which the admin will use immediately afterward to
set the real prices on the plans the migration creates inactive.

## 2. Catalog Restructure

### 2.1 Plan 6 ("2 Weeks", scroll, $3.00, group `2W-1U-Iran-5G`)

Recategorize in place: `UPDATE plans SET category = 'trip' WHERE id = 6`.
Same `plan_id`, same group, same price — this preserves its one existing
payment's `plan_id` reference and its display continues to work via the
existing `plan_name_2weeks` key. Trip becomes its own category, standing
alongside Scroll and Stream, with exactly one plan.

### 2.2 Plans 9, 10, 11 (old capped-Stream)

`UPDATE plans SET is_active = false WHERE id IN (9, 10, 11)`. Their IBSng
groups no longer exist, so they must disappear from Buy/Renew regardless
of the Manage Plans feature; setting `is_active=false` directly in this
migration (not waiting for the admin feature) achieves that immediately
on deploy. Rows stay in place for `Payment`/`VPNUser` FK history.

### 2.3 Four new plan rows (inactive, placeholder price)

Insert with `is_active=False` and `price_usd='0.00'` so they are
invisible to customers from the moment this migration runs. The admin
sets real prices and flips each to active via the Manage Plans feature
built in this same plan (Section 3) — nothing at a wrong or placeholder
price is ever customer-visible.

| name | category | duration_days | data_cap_mb | group_name | sort_order |
|------|----------|----------------|-------------|------------|------------|
| 3 Months | scroll | 90 | 30720 (30 GB) | 3M-1U-Iran-30G | 7 |
| 1 Month | stream | 30 | 0 (Unlimited) | 1M-1U-Iran-Unlimited | 8 |
| 2 Months | stream | 60 | 0 (Unlimited) | 2M-1U-Iran-Unlimited | 9 |
| 3 Months | stream | 90 | 0 (Unlimited) | 3M-1U-Iran-Unlimited | 10 |

`sort_order` 7-10 deliberately continue past the existing plans' 0-6
range (Trial=0, Trip/id6=1, Scroll-1M/id7=2, Scroll-2M/id8=3,
Stream-1M/id9=4, Stream-2M/id10=5, Stream-3M/id11=6) rather than
reusing 4-6, so the now-inactive old-Stream rows never collide with the
new ones in any listing that doesn't filter on `is_active` (i.e. the
Manage Plans admin list, which intentionally shows every row).

`data_cap_mb = 0` is the new sentinel for "Unlimited" (see §2.5) —
`data_cap_mb` stays a required, non-nullable `Integer` column; no schema
change to the column itself, only a new interpretation of one value.

Before inserting these, seed the 4 new group names into the `groups`
table (same frozen-literal `bulk_insert` pattern `0004` used), since
`Plan.group_name` is `ForeignKey("groups.name")`.

### 2.4 Plans 7, 8 (Scroll 1M/2M)

Untouched.

### 2.5 "Unlimited" data cap, bilingually

`app/services/catalog.py:format_data_cap` currently takes only
`data_cap_mb` and has no language awareness (units like "GB"/"MB" are
kept as literal Latin abbreviations in both languages, matching how
`{cap}`/`{price}` placeholders are never translated elsewhere in
`app/i18n/texts.py` — only fixed prose strings are). It gains a required
`lang: str` parameter:

```python
def format_data_cap(data_cap_mb: int, lang: str) -> str:
    if data_cap_mb == 0:
        return t("data_cap_unlimited", lang)
    if data_cap_mb % 1024 == 0:
        return f"{data_cap_mb // 1024} GB"
    return f"{data_cap_mb} MB"
```

New i18n key, added to `app/i18n/texts.py`'s "Plan display names"
section (both languages, matching every other `TEXTS` entry):

```python
"data_cap_unlimited": {"en": "Unlimited", "fa": "نامحدود"},
```

Every existing call site of `format_data_cap` must pass `lang` explicitly:
customer-facing call sites (`app/bot/keyboards/buy.py`,
`app/bot/keyboards/renew.py`) pass the caller's real `lang`; the new
Manage Plans admin screens (English-only, per Global Constraints) always
pass `lang="en"`.

### 2.6 New `trip` category

`app/services/catalog.py:CATEGORIES` gains `"trip"`:
`CATEGORIES = ("scroll", "stream", "trip", "trial")`.

New i18n key `category_trip` (`app/i18n/texts.py`, "Buy Subscription"
section, next to `category_scroll`/`category_stream`):

```python
"category_trip": {"en": "Trip", "fa": "سفر کوتاه"},
```

(`سفر کوتاه` = "short trip" — chosen for a single 2-week plan; goes
through the same translation review as every other Persian string in
this project before deploy.)

`_CATEGORY_KEYS` in `catalog.py` gains `"trip": "category_trip"`.

Both category-selection screens gain a Trip button alongside
Scroll/Stream:

- `app/bot/keyboards/buy.py:buy_category_keyboard` — add a third button,
  `callback_data="buy:category:trip"`, using `category_display_name("trip",
  lang)`.
- `app/bot/handlers/buy.py:buy_category_cb` — its category filter
  (`F.data.startswith("buy:category:")`) already matches `trip` with no
  change; verify the handler's category validation (if it whitelists
  `("scroll", "stream")` literally anywhere) is extended to include
  `"trip"`.
- `app/bot/keyboards/renew.py:renew_category_keyboard` — same addition,
  `callback_data=f"renew:category:{vpn_user_id}:trip"`.
- `app/bot/handlers/renew.py:renew_category_cb` — same category-filter
  check as buy.py.

## 3. Manage Plans Admin Feature

### 3.1 Scope

Admin-facing only (English-only strings, no `t()` calls anywhere in this
feature — see `CLAUDE.md`'s Conventions section). Edits **existing** Plan
rows only: `price_usd` and `is_active`. Never creates or deletes a Plan
row, and never edits `group_name` in this pass (noted as a deliberate
follow-up: reassigning a plan to a different IBSng group needs its own
review, e.g. confirming the target group actually exists in the local
`groups` table rather than accepting free-text input).

Gated behind `has_level(session, telegram_id, "full")`, matching every
other screen in `app/bot/handlers/admin_settings.py`.

### 3.2 Screens and callback namespace

Reuses the `adm:settings:*` namespace already established in
`admin_settings.py`/`admin.py`:

- `adm:settings:plans` — plan list, grouped by category in a fixed
  display order (`trial`, `scroll`, `stream`, `trip` — free tier first,
  then paid tiers low-to-high commitment, a natural order for an admin
  scanning prices), each row: `{name} ({duration_days}d, {data_cap
  display}) — {group_name} — {price} — {✅/🚫}`. Tapping a row opens its
  detail view: `adm:settings:plan:{id}`.
- `adm:settings:plan:{id}` — detail view: full field dump (name,
  category, duration_days, data cap, group_name, price_usd, is_active),
  plus two action buttons:
  - `adm:settings:plan:{id}:price` → FSM prompt for a new price.
  - `adm:settings:plan:{id}:toggle` → flips `is_active` immediately, no
    FSM, shows a one-line confirmation, re-renders the detail view.
  - Back button → `adm:settings:plans`.

### 3.3 Price-edit FSM

Mirrors `settings_edit_support_cb`/`settings_receive_support_username`'s
existing shape in `admin_settings.py` exactly: a
`callback_query` handler enters a new FSM state (e.g.
`AdminSettingsStates.editing_plan_price`, storing `plan_id` in FSM data),
prompts for text input, and a `message` handler bound to that state
validates and applies it.

Validation: must parse as a positive `Decimal`, reject non-numeric input
with a clear re-prompt (no state change), reject values `>= 1000`
("too high — enter a value under $1000") the same way, matching the
brief's own stated bound. On success: `catalog.update_plan(session,
plan_id, price_usd=new_price)` (already exists and does exactly this —
no service-layer change needed there), log the audit line (§3.5), clear
FSM state, re-render the plan detail view showing the new price.

### 3.4 Active toggle hides inactive plans from Buy/Renew

`catalog.list_plans(session, category=..., active_only=True)` already
defaults to `active_only=True` and is what `buy.py`/`renew.py` already
call — confirm both call sites pass no `active_only=False` override (they
don't, per the current file contents) so this "just works" the moment
`is_active` flips. No behavior change needed there; this sub-item is
verification, not new code, and gets its own test per §3.6.

### 3.5 Audit log

A structured log line (Python's `logging`, not a new table — no existing
audit table in this project), emitted from the price-edit handler after
`update_plan` succeeds:

```python
logger.info(
    "admin_price_change",
    extra={
        "admin_telegram_id": callback.from_user.id,
        "plan_id": plan_id,
        "old_price": str(old_price),
        "new_price": str(new_price),
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
    },
)
```

`old_price` is read from the `Plan` row before calling `update_plan`
(capture it before the call — `update_plan` mutates and commits the same
ORM instance).

### 3.6 Payment price-snapshot guarantee

`app/services/payments/service.py`'s `create_crypto_payment` already
reads `plan.price_usd` once at creation time and stores it as
`Payment.amount_usd` on the new row (not re-read later) — confirm this
by inspection during Task implementation, and add a regression test:
create a payment for a plan, change the plan's price via `update_plan`,
re-fetch the `Payment` row, assert `amount_usd` is unchanged from the
value at creation.

## 4. Global Constraints

- Customer-facing strings (Buy/Renew Trip button, `format_data_cap`'s
  Unlimited text) go through `app/i18n/texts.py`'s `t()`, both languages.
  Manage Plans is entirely admin-facing and uses plain English strings,
  never `t()`.
- The catalog migration never deletes a `Plan` or `Group` row that any
  `Payment` or `VPNUser` row references (verified against production
  data in §1) — retiring a plan means `is_active=False`, never a delete.
- The four newly inserted plan rows ship `is_active=False`; only an
  admin, via Manage Plans, makes them customer-visible.
- Manage Plans never creates or deletes a `Plan` row and never edits
  `group_name` in this pass (`app/db/models/plan.py`'s own docstring).
- `format_data_cap`'s new `lang` parameter is required (no default) —
  every call site in this plan already needs updating anyway (the two
  customer-facing keyboards, plus the new admin plan list/detail views),
  so there's no cross-task default-parameter risk like the bilingual-flows
  plan had.

## 5. Testing

- `test_catalog.py`: `format_data_cap(0, "en") == "Unlimited"`,
  `format_data_cap(0, "fa") == "نامحدود"`, existing GB/MB cases still
  pass with `lang` threaded through; `category_display_name("trip", lang)`
  for both languages; `CATEGORIES` contains `"trip"`.
- A new migration test (or extend the existing catalog seed test, if one
  covers `0004`) asserting: plan 6 is category `trip` after upgrade,
  plans 9/10/11 are `is_active=False`, the 4 new rows exist with
  `is_active=False` and `price_usd=0.00`, and no `plans` row was deleted
  (`SELECT count(*) FROM plans` only grows, never shrinks, across this
  migration).
- Buy/Renew flow tests: Trip category button appears and routes to its
  one plan; an `is_active=False` plan is absent from both category and
  plan listing screens.
- Manage Plans tests (new `tests/functional/test_admin_manage_plans.py`,
  following this project's `dispatcher` fixture + `fake_session.calls`
  convention): permission-denied for a sub-"full" admin tier, list
  screen renders all plans grouped by category, price-edit happy path,
  invalid price input (non-numeric and ≥$1000) is rejected with a
  re-prompt and no DB change, active-toggle immediately hides a plan from
  a subsequent Buy-flow query, and the Payment price-snapshot test from
  §3.6.
