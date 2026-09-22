# Admin Panel Restructure (Epic Part 1) — Design Spec

Date: 2026-09-23
Status: approved (menu tree confirmed in chat)
Part 1 of 5. Parts 2–5 (Financial, Users, Reports, admin log group) get
their own spec/plan pairs and depend on the tree this part establishes.

## 1. Why

The panel grew screen by screen and now shows the seams:

- **Settings holds nine items** mixing money (Manage Plans, Crypto
  Settlement, Crypto Coins, Recover Stuck Payments) with plumbing
  (Support Contact, Sync IBSng Groups, Mandatory Channel, Renewal
  Reminders, Trial Limit).
- **Discount Codes sits alone at the top level** with no financial
  sibling to group with, and two more financial screens (Revenue,
  Payments) are coming in Part 2 with nowhere to live.
- **Manage Admins occupies a top-level slot** for something touched
  rarely.

## 2. The tree

```
🛠 Admin Panel
├── 👤 Users                  [support+]  adm:users
├── 💰 Financial              [sales+]    adm:fin        (new)
├── 📊 Reports                [sales+]    adm:reports    (new, Part 4)
├── 📚 Tutorials & Profiles   [support+]  adm:tutorials
├── 📢 Broadcast              [full]      adm:broadcast
├── ⚙️ System                 [full]      adm:settings
└── ⬅️ Back to Menu                       menu:root
```

**Financial** (`adm:fin`): Revenue Overview and Payments are Part 2
placeholders in this part; Discount Codes (`adm:discounts`), Manage
Plans (`adm:settings:plans`), Crypto Settlement (`adm:settings:crypto`),
Crypto Coins (`adm:settings:coins`) and Recover Stuck Payments
(`adm:settings:reconcile`) move here from their current parents. The
last three stay full-admin-only and are hidden from a sales admin.

**System** (`adm:settings`, unchanged callback, renamed heading):
Support Contact, Mandatory Channel, Renewal Reminders, Trial Limit, Sync
IBSng Groups, plus Manage Admins (`adm:admins`) moved in from the top
level. The Admin Log Group screen joins it in Part 5.

**Users** and **Tutorials & Profiles** are untouched in this part; the
user-detail work is Part 3.

## 3. The compatibility rule

**No callback is renamed, added-to or removed in this part.** Every
existing `adm:*` string keeps working exactly as it does today. Only two
things change:

1. which keyboard lists which button, and
2. where a moved screen's "Back" button points.

This matters because a keyboard already sitting in an admin's chat
history is a live control surface: an admin who scrolls up and taps
"🏷 Discount Codes" on last week's panel must still land on the discount
list, not a dead end. It also keeps any external reference intact
without an audit.

Back-destination changes, which are the only user-visible break in
muscle memory:

| screen | Back was | Back becomes |
|---|---|---|
| Discount Codes list | adm:root | adm:fin |
| Manage Plans | adm:settings | adm:fin |
| Crypto Settlement | adm:settings | adm:fin |
| Crypto Coins | adm:settings | adm:fin |
| Recover Stuck Payments | adm:settings | adm:fin |
| Manage Admins | adm:root | adm:settings |

## 4. Permission tiers

Unchanged for every existing screen; the two new menus adopt the tier of
what they contain:

- `adm:fin` — sales and above. It holds pricing and revenue, which a
  support admin has no business seeing. Its three full-only children are
  **hidden** from a sales admin rather than filter-gated, matching the
  convention established for Broadcast: a visible button whose filter
  silently rejects the tap gives zero feedback.
- `adm:reports` — sales and above (Part 4 builds the screen; this part
  only adds the entry, which renders a "coming in Part 4" note).

The routers that own the moved screens keep their own gates
(`admin_discounts` is `IsSalesAdmin`, `admin_settings` is
`IsFullAdmin`), so moving a button cannot widen access.

## 5. Implementation shape

- `app/bot/keyboards/admin.py` gains `admin_financial_menu(*, is_full_admin)`
  and loses the moved entries from `admin_root_menu` and
  `admin_settings_menu`.
- `app/bot/handlers/admin.py` gains handlers for `adm:fin` and
  `adm:reports`, alongside the existing `adm:root` / `adm:users` /
  `adm:settings` / `adm:tutorials`. Both new handlers check
  `has_level(..., "sales")` inline, matching how `adm:root` and
  `adm:users` already gate themselves (that router has no router-level
  filter because it serves every tier).
- Back destinations change in `admin_discounts.py`, `manage_plans.py`,
  `crypto_settlement.py`, `admin_settings.py` (Crypto Coins, Recover
  Stuck Payments) and `admin_admins.py`.
- `admin_fallback.router` stays registered last, unchanged.

## 6. Tests

- The root menu shows exactly the seven entries for a full admin, and
  the right subset for sales and support.
- Financial lists its five moved entries for a full admin and hides the
  three full-only ones from a sales admin.
- A support admin tapping `adm:fin` or `adm:reports` gets the
  permission alert from `admin_fallback`, not a screen.
- Every moved screen is still reachable by its original callback, which
  is the compatibility rule above expressed as a test.
- Each moved screen's Back button points at its new parent.
