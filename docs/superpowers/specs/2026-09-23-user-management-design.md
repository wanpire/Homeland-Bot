# User Management (Epic Part 3) — Design Spec

Date: 2026-09-23
Status: approved (design reviewed in chat)
Part 3 of 5.

## 1. Scope

One screen that answers "who is this customer and what is going on with
them", reached by searching, with the actions an admin then wants
available from that same screen instead of from separate menu entries.

Today an admin helping a customer must know the IBSng username before
Renew is usable, and must go to a different screen to block someone,
with nothing anywhere showing what the customer has bought.

## 2. Users menu

```
👤 Users
├── 🔍 Find a User        (new)   adm:users:find
├── ♻️ Renew a Service     (existing, unchanged)   adm:users:renew
├── 🚫 Blocked Users       (existing, unchanged)   adm:users:blocked:0
└── ⬅️ Back to Admin Panel
```

Renew a Service stays as its own entry: it takes an IBSng username
directly, which is the right tool when an admin has a username from a
support ticket and no idea which Telegram account owns it.

## 3. Search

`adm:users:find` prompts, one FSM state, and accepts a Telegram ID, an
`@username` or a bare username. It reuses
`app/services/reporting.py`'s `resolve_user_query` rather than growing a
second parser, so Financial's payment search and this one can never
disagree about what `@someone` means.

A miss says so. It never falls back to a list.

## 4. The detail view (`adm:users:view:<telegram_id>`)

```
👤 @someone
Telegram ID: 179494847
First seen: 2026-09-15 · Language: fa
Status: active            (or: 🚫 blocked)
Trial: used               (or: not used)

Services (2)
• ir.d6jxur — 2 Weeks · active until 2026-10-06
• ir.ss8ak5 — Trial · expired 2026-09-16

Payments
Paid: 3 · $27.00 total · last 22 Sep
Pending: 1 · Failed: 2
```

Sources, each verified rather than assumed:

| line | source |
|---|---|
| identity, first seen, language, blocked | `BotUser` |
| trial used | `has_used_trial` |
| services | `VPNUser` rows joined to `Plan` |
| status and expiry | **IBSng, live**, via `get_service_status` |
| payments | `Payment` rows aggregated by status |

**Expiry must come from IBSng.** `VPNUser.expires_at` exists as a column
but nothing in the codebase ever writes it, so it is NULL for every row;
rendering it would show "no expiry" for a working account. My Services
already resolves this the same way. `get_service_status` never raises,
returning `("unknown", None)` on any IBSng error, so an IBSng outage
degrades one line rather than the screen — which matters, because the
outage of 2026-09-22 is exactly when an admin would open this.

A user with many services would mean many IBSng round trips, so the view
queries live status for at most the five most recent and notes when more
exist.

## 5. Actions on the detail view

- **🚫 Block / ✅ Unblock** — toggles via the existing
  `block_user(session, telegram_id, blocked)` and redraws the same
  screen. Replaces having to find the person on a separate screen.
- **♻️ Renew** per service — jumps into the existing renew flow with
  that service's username already filled in.
- **🧾 Payments** — opens Financial's payment list filtered to this
  user. Shown only to sales and above, since Financial is sales-gated;
  a support admin sees the counts on this screen and no link.

**The renew jump keeps the namespace guard.** `admin_renew` refuses any
IBSng username that is not in a Homeland group, because this IBSng
instance is shared with AloBot and renewing a mistyped username would
reset another business's customer. The jump re-runs that check rather
than trusting that a username stored in our own `vpn_users` table is
still in one of our groups — an account moved out of a Homeland group
since purchase is exactly the case the guard exists for.

## 6. Permissions

Users is support and above, unchanged. The Payments link is the only
sales-gated element, and it is hidden rather than shown-and-refused.

## 7. Shape

- `app/services/user_admin.py` (new) — `user_overview(session, client,
  telegram_id) -> UserOverview | None`, gathering everything in §4.
  Takes the IBSng client so the caller owns its lifetime and tests can
  pass the fake.
- `app/bot/keyboards/user_admin.py` (new) — detail keyboard and the
  search prompt.
- `app/bot/handlers/user_admin.py` (new router, `adm:users:find`,
  `adm:users:view:*`, `adm:users:toggleblock:*`, `adm:users:renewsvc:*`).
  Registered before `admin_fallback` and before `admin_block`, whose
  `adm:users:blocked:*` and `adm:users:unblock:*` prefixes do not
  collide.
- `app/bot/keyboards/admin.py` — the new Find a User entry.

## 8. Tests

- Search accepts an ID, `@username` and a bare username; a miss reports
  it and shows no list.
- The overview reports services with live status from the fake IBSng
  server, and still renders when IBSng errors, showing "unknown".
- Payment counts split by status and total only paid money.
- Trial used and not-used both render.
- Block toggles and the screen redraws with the opposite action.
- The renew jump refuses a username whose IBSng group is not Homeland's.
- A support admin sees the screen but no Payments link; a sales admin
  sees the link.
- A user with no services and no payments renders without crashing.
