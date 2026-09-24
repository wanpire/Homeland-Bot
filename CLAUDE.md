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
  pair (My Services); `deliver_device_setup()` is the handover's step 4.
  Neither sends credentials (that's the caller's job).
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
  `send_download_links`, which `deliver_setup` also composes for My
  Services and `deliver_device_setup` for the handover - never add a
  second path that sends this material.
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
- `app/services/payments/confirmation.py` - the ONE path from "invoice
  paid" to "service provisioned", used by both the Plisio callback and
  the reconciler.
- `app/services/handover.py` - the ONE handover sequence, run by trial,
  purchase and renewal alike: device → protocol (only those the device
  supports, per `protocols_for_platform` in `app/services/tutorials.py`;
  skipped when one is left, so Android goes straight to OpenVPN) →
  credentials (no buttons) → `deliver_device_setup` for that device only
  → the Tutorial/main-menu pair on whichever message came last. Pickers
  are `ho:<source>:<ref>:…` (`app/bot/handlers/handover.py`): `t` + the
  trial's `vpn_users.id`, or `p` + a `payments.id`, ownership-checked on
  every tap; the password never travels in callback data. A paid order
  sends its credentials the moment the payment activates, BEFORE the
  pickers (`HandoverAccount.credentials_sent_up_front`), so a paying
  customer never depends on a tap to learn them; the taps then send only
  the setup and the pair. Its device picker has no main-menu button,
  because that tap would edit away the route to the setup. Never build a second copy of this sequence or
  another Android/L2TP check; a new flow gets a new source. Old
  `trial:os`/`trial:platform`/`trial:protocol` buttons still work.
- My Services (`app/bot/handlers/myservices.py`, redesigned 2026-09-25 to
  AloBot's layout): root menu (`menu:myservices`: account list · Add new
  account = the Buy flow's own `menu:buy` · Back) → list labelled by
  USERNAME (`myservices:list`; plan names repeat, usernames don't) →
  per-account action menu (`myservices:view:<id>`: info · renew, hidden for
  trials · change password · change ownership) → info screen
  (`myservices:detail:<id>`, built by `app/services/account_view.py`).
  IBSng's `nearest_exp_date` is Gregorian and so is every screen - there
  is no Jalali anywhere. Persian "label: value" lines go through
  `app/i18n/bidi.py`'s `info_line` (RLM + FSI…PDI, marks outside
  `<code>`); never hand-build a Persian credential line.
- Reset Password (`myservices:pw`/`pwdo`) = AloBot's: confirm first, once
  per 30 days (`password_changed_at`), `reset_vpn_password` locks the
  row, re-checks `is_homeland_group`, then the single IBSng path. Not
  logged (AloBot doesn't).
- Change Ownership (`app/bot/handlers/ownership.py`,
  `app/services/ownership.py`): ownership = `vpn_users.telegram_id`, as in
  AloBot, but the account moves ONLY when the named recipient accepts
  (`ownership_transfers` row, 24h expiry, owner can cancel, newest offer
  supersedes older ones, every tap re-checked under row locks). Accepting
  clears `password_changed_at` so the new owner can lock the old one out
  at once, and posts an `OWNERSHIP` entry (🔑 Accounts topic). AloBot's
  version moves instantly on the owner's word; never regress to that.
- `app/services/openvpn_setup.py` - My Services' OpenVPN resend: the
  .ovpn config, then four platform buttons (`ovpn:link:<id>`), and only
  the tapped platform's download link. It looks up NO guide: none
  exists for OpenVPN, and the lookup's "not ready" answer was reaching
  customers mid-purchase. `deliver_setup` passes
  `notify_if_missing=False` for the same reason; Tutorials keeps the
  default, where "not ready" answers an explicit request.
- `app/services/delivery.py` - the ONE account-delivery message, step 3
  of the handover for all three flows (purchase, renewal, trial). Only
  the headline differs; it carries no buttons (the pair ends the
  sequence), and the body and tap-to-copy credentials are shared, so
  never build this text anywhere else. Callers
  pass `data_cap_mb` themselves: a paid order passes the snapshot on its
  payment, a trial passes the trial plan's value. A purchase carries its
  password; a renewal and a trial read it back from IBSng, and an
  unreadable one degrades to the no-password variant rather than looking
  like a failure.
  `UNLIMITED_PLAN_IBSNG_CREDIT` in `app/services/vpn_users.py` is the
  flat credit for unlimited plans (100); metered plans keep passing
  their own data cap, which is what caps that buyer. `app/services/payments/reconcile.py` sweeps every open
  payment against Plisio's own record and finishes any it calls
  completed: on 2026-09-22 a real payment was stranded because IBSng was
  down when the callback arrived and Plisio stopped retrying, and nothing
  would ever have recovered it.
- `app/logging_setup.py` - redacts secrets from EVERY logger, including
  third-party ones. Plisio takes its key as a query parameter and httpx
  logs full URLs at INFO, which leaked the live key into the container
  logs until this landed.
- Admin panel tree (regrouped 2026-09-23): Users · Financial · Reports ·
  Tutorials & Profiles · Broadcast · System. Financial holds Discount
  Codes, Manage Plans and the crypto screens; System holds the plumbing
  plus Manage Admins. **Never rename an `adm:*` callback** - a keyboard
  sitting in an admin's chat history is a live control surface, so
  screens are re-parented (which menu lists them, where Back points)
  and never renamed. A button a tier cannot use is hidden, not
  shown-and-filtered; a handler that refuses a tap itself must say so,
  because it consumes the callback and `admin_fallback` never sees it.
- `app/services/reporting.py` - the ONE definition of revenue and of a
  reporting period, read-only and free of aiogram imports so the
  Financial screens and the Reports screen cannot drift. Revenue means
  `status == "paid"` and nothing else, dated by `resolved_at` falling
  back to `created_at`. Refunds are reported if they appear but no
  refund action exists: nothing in the codebase can set that status.
- `app/services/user_admin.py` - one customer's full picture for the
  admin detail view. **Never read `VPNUser.expires_at`**: nothing in the
  codebase writes it, so it is NULL for every row and would read as "no
  expiry" for a live account. Status and expiry come live from
  `get_service_status`, which never raises. Any path that renews an
  IBSng account must re-run `is_homeland_group` first, including one
  starting from our own `vpn_users` row: the instance is shared with
  AloBot and an account moved out of a Homeland group is exactly what
  that guard catches.
- `app/services/adminlog.py` - the ONE format and sender for the
  operational log group. Never call `bot.send_message` for logging or
  compose an entry elsewhere; adding a category is one `EVENTS` entry
  plus one call site. `log_event` never raises and returns immediately
  when `ADMIN_LOG_CHAT_ID` is blank, so logging can never break a flow.
  The group is a forum: each `EventType` names a `topic`, and
  `app/services/logtopics.py` creates that topic on first use and stores
  its thread id in `app_config` (`log_topic:<category>`) - never
  hardcode a thread id. A topic that cannot be created falls back to the
  general thread rather than dropping the entry. `/logtopics` (full
  admins) creates any missing topic and is safe to re-run.
  `app/services/scheduled_reports.py` posts service + server health
  hourly (a heartbeat in a dedicated topic is reassurance, not noise;
  `health.py` still posts immediately on a state change) and the
  accounting summary daily at 08:00 UTC, from the same `reporting.py`
  queries the Reports screens read. `app/services/backup.py` runs the
  nightly pg_dump whose result that group reports.
- Reports (`adm:reports`) is a menu: Overview, Signups, Sales,
  Accounting (each with the period selector, `adm:reports:<kind>:<period>`),
  Service Health, Server Health, Backups. Sales-gated throughout.
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
