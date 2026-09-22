# User Management Implementation Plan (Epic Part 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Find a customer by ID or username and see everything about them on one screen, with block and renew available from it.

**Architecture:** A gathering service returns one dataclass; a new router renders it. Search reuses Financial's `resolve_user_query`; expiry comes live from IBSng because the local column is never written; the renew jump re-runs the existing namespace guard.

**Tech Stack:** Python 3.12, aiogram 3.x, SQLAlchemy 2.0 async, pytest in the isolated Docker stack.

**Spec:** `docs/superpowers/specs/2026-09-23-user-management-design.md`

## Global Constraints

- Admin text stays English, never `t()`.
- **Never read `VPNUser.expires_at`**: nothing writes it, so it is NULL everywhere. Live status comes from `get_service_status`, which never raises.
- The renew jump must re-run `admin_renew`'s Homeland-group guard. This IBSng instance is shared with AloBot and renewing a foreign account would reset another business's customer.
- Search parsing stays in `reporting.resolve_user_query`; do not write a second parser.
- Users is support and above; the Payments link is sales-gated and hidden, not shown-and-refused.
- Registered before `admin_fallback`; thin handlers, async only, type hints.
- Run the suite with `make test`, or the sync-and-run fallback used by the other parts.

---

## File Structure

- **Create** `app/services/user_admin.py` — `user_overview`.
- **Create** `app/bot/keyboards/user_admin.py`, `app/bot/handlers/user_admin.py`, `app/bot/states/user_admin.py`.
- **Modify** `app/bot/keyboards/admin.py` — Find a User entry.
- **Modify** `app/main.py` — register the router.
- **Create** `tests/functional/test_user_admin.py`.

---

## Task 1: The overview service

**Interfaces:** `user_overview(session, client, telegram_id) -> UserOverview | None` with `ServiceLine(username, plan_name, status, expires_at)` and `PaymentTotals(paid, pending, failed, total_paid_usd, last_paid_at)`.

- [ ] **Step 1: Write the failing tests** covering: a user with services reports live status from the fake IBSng server; an IBSng error yields "unknown" rather than raising; payment totals split by status and sum only paid rows; trial used and not used; an unknown telegram_id returns None; a user with nothing renders empty collections.

- [ ] **Step 2: Run to verify it fails** — `ModuleNotFoundError: app.services.user_admin`.

- [ ] **Step 3: Write the service.** Gather `BotUser`, `has_used_trial`, `VPNUser` joined to `Plan` (newest first, live status for at most five via `get_service_status`), and a `Payment` aggregate grouped by status. Record `truncated_services` when more than five exist so the screen can say so.

- [ ] **Step 4: Run and commit.**

```bash
git add app/services/user_admin.py tests/functional/test_user_admin.py
git commit -m "feat: gather a customer's full picture for the admin detail view"
```

---

## Task 2: Search, detail screen and actions

**Interfaces:** callbacks `adm:users:find`, `adm:users:view:<telegram_id>`, `adm:users:toggleblock:<telegram_id>`, `adm:users:renewsvc:<vpn_user_id>`.

- [ ] **Step 1: Write the failing tests** covering: the Users menu lists Find a User; search by ID, `@username` and bare username each reach the detail view; a miss reports it; the detail view shows services, payments and trial state; block toggles and redraws with the opposite label; a support admin sees no Payments link while a sales admin does; the renew jump refuses a non-Homeland group.

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Build the keyboards, states and router.** The renew jump loads the `VPNUser`, calls `client.get_user_group`, refuses unless `is_homeland_group`, then sets `AdminRenewStates.plan` with the username in FSM data and renders `admin_renew_plan_keyboard`, so the existing execute step runs unchanged.

- [ ] **Step 4: Add the menu entry and register the router.**

- [ ] **Step 5: Full suite, then commit.**

```bash
git add app tests
git commit -m "feat: user search and a single customer detail view"
```

---

## Task 3: Docs and deploy

- [ ] **Step 1: CLAUDE.md** — record that `VPNUser.expires_at` is never written and live status is the only source, and that any renew path must re-run the Homeland-group guard.
- [ ] **Step 2: Deploy** and search for your own Telegram ID to confirm the view.

---

## Self-Review

- **Spec coverage:** §2 menu → Task 2 Step 4; §3 search → Task 2; §4 detail and its sources → Task 1; §5 actions and the guard → Task 2 Step 3; §6 permissions → Task 2; §7 shape → Tasks 1–2; §8 tests → each task's first step.
- **Placeholder scan:** the tests are described by their assertions rather than quoted in full, which is a deliberate compression for a part whose risk sits in the service, not the rendering; the two load-bearing rules (never read `expires_at`, always re-run the group guard) are stated as constraints so they cannot be missed.
- **Type consistency:** `user_overview(session, client, telegram_id)` takes the IBSng client from its caller, matching how `myservices.py` already opens one; `resolve_user_query(session, raw)` is imported, not redefined.
