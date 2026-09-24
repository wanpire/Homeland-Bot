# My Services Screens: Root Menu, Account Menu, Account Info, Username List — Design Spec

Date: 2026-09-25
Status: approved (requested directly; open points confirmed with the owner)
Related: `2026-09-16-my-services-design.md`, `2026-09-25-reset-password-design.md`,
`2026-09-25-change-ownership-design.md`. Mirrors AloBot's My Services
(`~/AloBot/app/bot/handlers/users.py`, `app/bot/keyboards/menus.py`).

## 1. Summary

```
menu:myservices          🛍️ My Services — pick an option
  ├─ 📋 My accounts       → myservices:list
  ├─ ➕ Add new account   → menu:buy   (the existing Buy entry)
  └─ 🔙 Back to menu      → menu:root

myservices:list          one button per account: "{username} — {status}"
  └─ 🔙 Back             → menu:myservices

myservices:view:<id>     account action menu (new in Homeland, AloBot's layout)
  ├─ 🗓 View account info       → myservices:detail:<id>
  ├─ ♻️ Renew or upgrade        → renew:service:<id>  (not for trials)
  ├─ 🔑 Change password         → myservices:pw:<id>
  ├─ 🔄 Change ownership        → myservices:xfer:<id>
  ├─ 🔙 Back                    → myservices:list
  └─ 🔙 Back to menu            → menu:root

myservices:detail:<id>   the account-info screen (§3)
  ├─ 🔄 Resend Setup            → myservices:resend:<id> (unchanged flow)
  └─ 🔙 Back                    → myservices:view:<id>
```

## 2. Findings that shaped this

- **The action menu did not exist in Homeland.** The request described
  it as existing; it is AloBot's. Homeland's `myservices:view` went
  straight to the details, with only Resend Setup. It is built here with
  AloBot's buttons, and Resend Setup moves onto the info screen so the
  feature is kept.
- **"Add new account" goes to Buy, as requested.** AloBot's button of the
  same name instead claims an existing IBSng account by username and
  password. It is deliberately not ported.
- **Calendar.** IBSng's `nearest_exp_date` is Gregorian at the source
  (`"YYYY-MM-DD HH:MM"`, e.g. `2026-09-23 15:41`, confirmed live on this
  shared instance; a Jalali year would read 1405). Homeland has no Jalali
  code anywhere, so every screen already shows Gregorian dates. This
  screen is therefore not an exception and needs no conversion. It
  formats the parsed datetime explicitly as Gregorian `YYYY-MM-DD HH:MM`,
  keeping the existing "UTC" label other screens use.

## 3. Account-info screen

```
{plan_name} 🔑
{Status}: {emoji} {status text}
{Volume}: {Unlimited | 10 GB}          ← format_data_cap, as in the delivery template
{Expires}: 2026-10-23 15:41 UTC | "starts at first connection" | —

{Username}: <code>{username}</code>
{Password}: <code>{password}</code>    ← or the "unavailable" line
```

Plan name comes from `plan_display_name`, falling back to the IBSng
group. Status comes from `get_service_status`, which never raises, and
the password from `get_user_password`, which is guarded. Nothing is
hardcoded.

### Bidi fix

In Persian, a line is a right-to-left label followed by a left-to-right
value. Clients that resolve the line's direction from its content can
lay the value out wrongly, or align the line to the left. Each Persian
info line is therefore built by one helper (`app/i18n/bidi.py`):

- it starts with U+200F RIGHT-TO-LEFT MARK, which pins the line as RTL
  and right-aligned whatever the value contains;
- the value is wrapped in U+2068 FIRST STRONG ISOLATE … U+2069 POP
  DIRECTIONAL ISOLATE, so the value's own direction cannot reorder the
  label or the colon.

The marks sit outside `<code>`, so tap-to-copy copies the bare value.
English lines are left untouched. The fix is verified by the owner on
real clients: the production bot sends sample screens (fake
credentials) to the owner's own Telegram account.

## 4. Account list

Each button reads `{ibsng_username} — {status}`. The username is unique
per account, so there are no more identical rows of "Free trial —
pending". The status comes from `get_service_status`, as before.

## 5. Tests

Root menu buttons and targets; Add new account → `menu:buy`; list labels
are username-first and distinct for several trials; action menu buttons
(no renew for a trial); info screen fields (plan, volume, Gregorian
expiry, pending/unknown variants, tap-to-copy spans); Persian lines
carry RLM + isolates with the marks outside `<code>`; English lines carry
no marks; unowned id → not found; Resend Setup still reachable.
