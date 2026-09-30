# Sales Toggle (Disable Sales + custom message) — Design Spec

Date: 2026-09-30
Status: approved (design reviewed in chat)

An emergency/maintenance switch that stops every new sale — purchases,
renewals, and trial activations — without stopping the bot. While it is
on, a customer who picks something sees an admin-written message
instead of an invoice or an account.

## 1. Decisions

| Question | Decision |
|---|---|
| Where the block appears | After selection: tapping a specific plan (Buy/Renew) or tapping Trial in the main menu. Menus and category lists stay visible and unchanged. |
| Stale buttons | The confirm handlers re-check, so an old `buy:confirm` / `renew:confirm` / `trial:confirm` button in chat history cannot slip past. |
| Invoice created before the switch, paid while it's on | Honored. The payment-confirmation path and the reconciler are untouched: the customer has paid, they get their service. |
| Admin label language | English, like every other `adm:*` screen (CLAUDE.md convention). |
| Who can use it | Full admins only, like the other state-changing Financial controls. Sales-tier admins don't see the button. |
| Log topic | A new `🛠 Admin Actions` topic, not Accounting (that one holds the automated daily summaries). |

## 2. Storage and service — `app/services/sales_status.py` (new)

Backed by the existing `app_config` key/value table, the same way the
Mandatory Channel toggle is. No migration.

| Key | Meaning |
|---|---|
| `sales_enabled` | `"true"` / `"false"`. **Absent means enabled**, so deploying this changes nothing until an admin flips it. |
| `sales_paused_message_fa` | Admin's Persian text. Absent or empty → default. |
| `sales_paused_message_en` | Admin's English text. Absent or empty → default. |

The positive name (`sales_enabled`, default True) is deliberate: the
admin screen says "Sales: enabled/disabled", the code says
`are_sales_enabled`, and there is no double negative anywhere.

API (async, typed, no aiogram imports):

- `are_sales_enabled(session) -> bool`
- `set_sales_enabled(session, enabled: bool) -> None`
- `get_custom_paused_message(session, lang) -> str | None` — the stored
  text or None.
- `set_custom_paused_message(session, lang, text) -> None`
- `clear_custom_paused_messages(session) -> None` — both languages back
  to default.
- `sales_paused_text(session, lang) -> str` — what the customer sees:
  the custom text for `lang` (HTML-escaped) if set, otherwise
  `t("sales_paused_default", lang)`. An unknown `lang` follows `t()`'s
  own English fallback, and the custom lookup uses `en` for it too.

Custom text is plain text: stored as typed, escaped on render, so an
admin typing `<` cannot break the HTML parse mode. Maximum 3500
characters (leaves room under Telegram's 4096 limit and fits
`app_config.value`'s 4096).

## 3. The one gate — `app/bot/sales_gate.py` (new)

```python
async def block_if_sales_paused(callback: CallbackQuery, lang: str) -> bool:
```

Checks the flag. When sales are enabled it returns False and does
nothing. When they are disabled it renders `sales_paused_text` on the
tapped message through `show_screen` (so it also works on an Ad
Campaign photo, whose buttons reuse `menu:trial`), with a single
button `t("back_to_main_menu", lang)` → `menu:root`, answers the
callback, and returns True. The caller simply returns.

Called at the top of exactly these six handlers, and nowhere else:

| Flow | Block shown | Re-check |
|---|---|---|
| Buy | `buy:plan:<id>` (`buy_plan_cb`) | `buy:confirm:<id>` (`buy_confirm_cb`) |
| Renew | `renew:plan:<vpn>:<id>` (`renew_plan_cb`) | `renew:confirm:<vpn>:<id>` (`renew_confirm_cb`) |
| Trial | `menu:trial` (`trial_entry_cb`) | `trial:confirm` (`trial_confirm_cb`) |

The sales check runs before any other check in those handlers (plan
existence, trial eligibility), so a paused bot always answers with the
paused message, and never reaches Plisio or IBSng.

**Not gated** (explicitly): `menu:buy`, `menu:renew`, category screens,
`renew:service:*`, My Services and everything under it (info, reset
password, change ownership, OpenVPN resend), Tutorials, the handover
pickers for accounts already created, `app/services/payments/confirmation.py`,
the reconciler, the Plisio webhook, and admin manual renew.

### New i18n keys (`app/i18n/texts.py`, fa + en)

- `sales_paused_default`
  - en: "⏸ <b>Sales are temporarily paused.</b>\n\nNew purchases, renewals
    and trial activations are unavailable right now. Your active
    services keep working as usual. Please try again later."
  - fa: "⏸ <b>فروش موقتاً متوقف شده است.</b>\n\nدر حال حاضر امکان خرید،
    تمدید یا فعال‌سازی سرویس تست وجود ندارد. سرویس‌های فعال شما بدون
    تغییر کار می‌کنند. لطفاً کمی بعد دوباره تلاش کنید."
- `back_to_main_menu`
  - en: "🔙 Back to Main Menu"
  - fa: "🔙 بازگشت به منوی اصلی"

## 4. Admin screen — Financial → `🛑 Sales Status`

New router `app/bot/handlers/admin_sales.py` (English only, filtered
with `IsFullAdmin`), keyboard in `app/bot/keyboards/admin_sales.py`,
FSM states in `app/bot/states/admin_sales.py`. The Financial menu
lists the button for full admins only (`admin_financial_menu`'s
existing `is_full_admin` branch).

Callbacks (new, so nothing existing is renamed):

| Callback | Action |
|---|---|
| `adm:fin:sales` | Status screen |
| `adm:fin:sales:set:off` / `:set:on` | Set the flag to that value, log it if it changed, re-render |
| `adm:fin:sales:msg:fa` / `:msg:en` | Prompt for that language's text (FSM) |
| `adm:fin:sales:reset` | Clear both custom messages, re-render |

Status screen:

```
🛑 Sales Status

State: 🟢 Sales enabled            (or 🔴 Sales disabled)

Message shown to customers while disabled:

🇮🇷 FA (custom|default):
<preview>

🇬🇧 EN (custom|default):
<preview>
```

A custom preview is the escaped text, truncated to 200 characters; the
default is shown in full (it is short, fixed, and already valid HTML).

The switch buttons name the state they SET rather than flipping the
current one: a stale "Disable Sales" button tapped after another admin
already disabled sales must not turn them back on. A tap that changes
nothing re-renders the screen and logs nothing.

Buttons: `🔴 Disable Sales` or `🟢 Enable Sales` (whichever applies) ·
`✏️ Edit Message (FA)` · `✏️ Edit Message (EN)` · `↩️ Reset Messages
to Default` · `⬅️ Back to Financial` (`adm:fin`).

Editing: the prompt says which language and the length limit, with a
`❌ Cancel` button back to `adm:fin:sales`. Empty or non-text input,
or text over 3500 characters, is refused with the prompt kept open.
On success the state clears and the status screen is sent again as a
new message.

The `adm:fin:sales` prefix sits under `financial.py`'s
`adm:fin:payments:` / `adm:fin:payment:` / `adm:fin:revenue` handlers.
None of their filters match `adm:fin:sales…`, so the routers don't
collide.

## 5. Logging

New entry in `app/services/adminlog.py`:

- `SALES_STATUS = "sales_status"`, `EventType(SALES_STATUS, "🛑",
  "SALES STATUS", ("State", "Admin"), TOPIC_ADMIN_ACTIONS, "🛠 Admin Actions")`
- `TOPIC_ADMIN_ACTIONS = "admin_actions"`

Posted from the set handler after the flag is saved, only when it changed:
`State` = `🔴 DISABLED` or `🟢 ENABLED`, `Admin` = `@username (id)` or
the id alone. The timestamp is `render_event`'s own `Time:` line. The
topic is created on first use by `logtopics.resolve_thread_id`, and
`/logtopics` picks it up because it iterates `EVENTS`. `log_event`
never raises, so a logging failure cannot undo the toggle. Message
edits and resets are not logged.

## 6. Tests

Functional tests, in the existing `tests/functional` style:

- `test_sales_status.py` (service): defaults to enabled; the toggle
  persists across fresh sessions (a restart reads from the DB); custom
  message per language; default fallback in fa and en when unset or
  cleared; HTML in custom text is escaped.
- `test_sales_gate.py` (flows): with sales disabled, each of the six
  gated handlers shows the paused message with the back button and
  creates no payment, no invoice and no VPN user (Plisio and IBSng
  fakes are not called). With sales enabled, the same handlers behave
  as before. The custom message appears in the user's language.
- Unaffected: with sales disabled, `menu:buy`, `menu:renew`,
  `menu:myservices`, the account list, the account detail and reset
  password still work; the payment-confirmation path still provisions a
  pre-existing invoice.
- `test_admin_sales.py` (admin): the Financial menu shows the button to
  full admins and hides it from sales admins; the toggle flips and
  re-renders; a stale set that changes nothing logs nothing; the log event is sent with State and Admin; editing fa/en
  stores the text; empty and oversized text are refused; reset restores
  the defaults; cancel clears the FSM.
- Existing i18n parity tests cover the new keys in both languages.

Done means the full `make test` suite passes.

## 7. Documentation

CLAUDE.md gains one Architecture bullet: `sales_status.py` +
`sales_gate.py` is the ONE sales switch, the six gated handlers, and
the explicit rule that paid-invoice confirmation is never gated.
