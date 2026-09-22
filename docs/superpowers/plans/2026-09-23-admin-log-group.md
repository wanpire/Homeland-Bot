# Admin Log Group Implementation Plan (Epic Part 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An operational log group carrying six event categories in a consistent, scannable format, plus the nightly backup whose results it reports.

**Architecture:** One module owns the format and the sending; call sites pass values only. Health and backup run on the existing background-loop pattern. Health posts on state change, not on every check.

**Spec:** `docs/superpowers/specs/2026-09-23-admin-log-group-design.md`

## Global Constraints

- **Logging must never break a flow.** Every send is wrapped; a bad chat id or a removed bot is logged locally and swallowed.
- Blank `ADMIN_LOG_CHAT_ID` disables the feature entirely, so tests and local runs are unaffected.
- No caller composes a log message or calls `bot.send_message` for logging; adding a category is one `EVENTS` entry plus one call site.
- Health posts only on state change plus a daily heartbeat. A check that says "all ok" every 15 minutes is exactly the noise this replaces.
- English only, async only, type hints, no hardcoded secrets.
- Run the suite with `make test` or the sync-and-run fallback.

---

## Task 1: The event abstraction

- [ ] **Step 1: Write failing tests** for: each category's emoji, title and field order; omitted empty fields; HTML escaping; silent return when unset; a Telegram failure swallowed.
- [ ] **Step 2: Run to verify it fails.**
- [ ] **Step 3: Write** `app/services/adminlog.py` with `EventType`, `EVENTS`, `render_event` and `log_event`, plus `admin_log_chat_id` in `app/config.py` and `.env.example`.
- [ ] **Step 4: Run and commit.**

## Task 2: Call sites

- [ ] **Step 1: Write failing tests** that a new user, a purchase, a renewal and a trial each produce exactly one entry of the right category, and that a logging failure does not break the flow.
- [ ] **Step 2: Wire** `user_tracking` (new rows only), `confirmation` (purchase and renewal, so reconciler-recovered payments are logged too) and `trial`.
- [ ] **Step 3: Run and commit.**

## Task 3: Health loop

- [ ] **Step 1: Write failing tests** for: a state change posting, an unchanged state staying silent, a recovery posting, and a failing component not raising.
- [ ] **Step 2: Write** `app/services/health.py` with `check_all` and `run_health_loop`, state in Redis, registered in `app/main.py` beside the other loops.
- [ ] **Step 3: Run and commit.**

## Task 4: Nightly backup

- [ ] **Step 1: Write failing tests** for the success and failure report shapes, with the dump command stubbed.
- [ ] **Step 2: Write** `app/services/backup.py` (`run_backup_once`, `run_backup_loop` at 03:00 UTC, 14-day retention) and add the `/backups` volume to `docker-compose.yml`.
- [ ] **Step 3: Run and commit.**

## Task 5: Deploy and verify

- [ ] Set `ADMIN_LOG_CHAT_ID=-1004466777356` on the server, deploy, and post a test entry of each category to confirm the bot can write to the group.
- [ ] Run one backup manually and confirm the file, the retention count and the log entry.

---

## Self-Review

- **Spec coverage:** §2 abstraction → Task 1; §3 never-break → Task 1 and its tests; §4 call sites → Task 2; §5 health → Task 3; §6 backup → Task 4; §7 config → Task 1; §8 tests → each task's first step.
- **Placeholder scan:** tasks are described by assertion and component rather than quoted in full, matching parts 3 and 4; the two rules most easily lost (never break a flow, post only on change) are carried as constraints.
- **Type consistency:** `log_event(bot, key, **values)` is the only entry point; health and backup call it with their own keys rather than formatting anything themselves.
