# CLAUDE.md

Homeland - a Telegram bot selling reverse VPN (Iran-based IPs) in USD to
Iranian customers abroad. Bootstrapped from AloBot (`/Users/peyman/telegram-bot`,
a sibling project selling the opposite direction of VPN in Toman), trimmed
to a flat catalog (Scroll/Stream categories + a trial tier) with
bilingual (fa/en) customer-facing text and Stripe/crypto payments. Shares one IBSng instance
with AloBot - see the group-namespace isolation note below, non-negotiable.
See `docs/superpowers/specs/2026-09-14-homeland-bot-design.md` for the full
design and `docs/superpowers/plans/` for implementation plans.

## Stack
Python 3.12+, aiogram 3.x (async), PostgreSQL + SQLAlchemy 2.0 + Alembic,
Redis (FSM), pydantic-settings, Docker Compose.

## Architecture
- `app/bot/handlers/` - one router per domain, registered in `app/main.py`.
- `app/services/ibsng/client.py` - the ONLY place that calls the IBSng API.
  Same server AloBot uses, Homeland's own ISP name/credentials/groups.
  `user_balance.getUserBalanceInfoByUserID` is confirmed dead on this
  server - never use it; see the module docstring and spec §5/§14 for the
  quota-data plan instead.
- `app/db/models/plan.py` - the 7 fixed sale plans (Trial + 3 Scroll +
  3 Stream, see spec §4), seeded via migration `0002_catalog.py` then
  corrected to the real IBSng groups by `0004_correct_catalog_to_real_groups.py`.
  A flat `category` field (scroll/stream/trial), no location/user-count
  matrix like AloBot's `Service`.
- `app/services/groups.py` - `sync_groups()` is the ONLY code path that
  populates the local `groups` table from IBSng, and it filters to
  Homeland's own group-name namespace before upserting anything. This
  IBSng instance is SHARED with AloBot (a separate bot project with its
  own groups) - never remove or bypass that filter, and any future code
  that lists IBSng groups directly must apply the same one. See spec §14.
- `app/services/vpn_users.py` - the ONE account-creation path
  (`create_vpn_user`), shared by the trial flow and (later) Buy/Renew.
  Both local uniqueness checks run BEFORE the IBSng call so a request
  the DB is going to reject never provisions an orphan account on the
  shared IBSng instance.
- `app/services/tutorial_delivery.py` - `deliver_setup()` sends the
  OpenVPN profile + guide + download link for a (protocol, platform)
  pair. Shared by the trial flow now, Buy/Renew later; it deliberately
  does NOT send credentials (that's the caller's job).
- `/admintutorials` (`app/bot/handlers/tutorial_admin.py`) - the admin
  flow for uploading guides, OpenVPN profiles, and download links.
  Standalone command, gated by `has_level(..., "support")`, listed in
  `set_my_commands`; it will become a button on the general `/admin`
  panel when that sub-project lands.
- `app/services/broadcast.py` - the ONE outbound mass-messaging
  pipeline (recipient rules, pacing, failure counts, summary DM). The
  admin Broadcast button opens a submenu: Announcement
  (`app/bot/handlers/broadcast.py`, plain message) and Ad Campaign
  (`app/bot/handlers/campaign.py`, photo/text + optional single button
  whose callback data is the main menu's own `menu:<key>`). Never add a
  second send loop; extend `run_broadcast` instead.
- `app/bot/keyboards/menus.py`'s `show_screen()` - main-menu section
  entry handlers (`menu:buy/renew/trial/myservices/support`) render
  through it, not `edit_text`, because a campaign photo's button reuses
  their callback data and Telegram can't edit a photo into a text screen.
- `app/bot/handlers/tutorials.py` - the customer Tutorials section
  (`menu:tutorials`, `tut:*`). Protocol first, then device, for EVERY
  protocol including OpenVPN (whose guide falls back to the generic
  upload when no per-device one exists). The guide is sent automatically;
  the download link and OpenVPN profile are separate buttons, rendered
  only when that content exists. All sending goes through
  `app/services/tutorial_delivery.py`'s `send_guide` / `send_profile` /
  `send_download_links`, which `deliver_setup` also composes for Trial
  and My Services - never add a second path that sends this material.
- `app/services/payments/plisio.py` - the ONLY place that talks to
  Plisio. GET-only API (`api_key` as a query param, `{"status","data"}`
  envelopes, so a failure can arrive with HTTP 200), and ONE secret key
  that both authenticates calls and signs callbacks. Callbacks are
  verified with HMAC-SHA1 over the JSON body minus `verify_hash`, which
  travels INSIDE the body - so `PLISIO_CALLBACK_URL` must end in
  `?json=true`. Invoices name every accepted coin via `allowed_psys_cids`
  and the buyer picks one on Plisio's page, so there is deliberately NO
  per-coin minimum check in this codebase - see
  `docs/superpowers/specs/2026-09-22-plisio-migration-design.md` §4.
  Coins come from `PLISIO_PAY_CURRENCIES`.
- `app/config.py` - single `Settings` source of truth, loaded from `.env`.
  No hardcoded secrets, ever.
- FSM state lives in Redis (`app/redis.py`).

## Conventions
- Async only - no blocking I/O in handlers or services.
- Type hints on every function signature.
- Customer-facing strings are bilingual (fa/en) via app/i18n/texts.py's
  t(key, lang) - see docs/superpowers/specs/2026-09-18-bilingual-customer-
  flows-design.md. Admin-facing strings (everything under
  app/bot/handlers/admin*.py, admin_settings, admin_block, broadcast,
  tutorial_admin, and the adm:* screen tree) stay English-only - never
  route an admin-only string through t().
- IBSng operations (create/renew user) must be idempotent.
- Keep handlers thin: parse input, call a service, reply.
- New feature = new router + new service method, not a growing god-file.
- Every interactive flow/menu includes a "Back" button by default.

## Commands
`make setup` (generate .env) · `make up` / `make down` · `make migrate` ·
`make logs` · `make bot` (run locally) · `make test` (isolated test stack)
