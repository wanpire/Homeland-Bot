# Topic-Structured Logging and Expanded Reports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** File every operational event into its own forum topic, expand Reports into seven screens, and schedule health, backup and accounting posts.

**Architecture:** `adminlog` gains topic routing with ids discovered at runtime and stored in `app_config`. All screens and all scheduled posts read one query layer.

**Spec:** `docs/superpowers/specs/2026-09-24-topic-logging-and-reports-design.md`

## Global Constraints

- **Thread ids are never hardcoded**: created on demand via `createForumTopic` and stored in `app_config` under `log_topic:<category>`.
- A log entry is never lost: if a topic cannot be created, send to the general thread.
- `log_event` still never raises and is still inert when `ADMIN_LOG_CHAT_ID` is blank.
- One query layer: no statistic is computed twice in two places.
- Reuse the existing background-loop pattern; no new scheduler.
- Admin text English-only, async only, type hints, thin handlers.
- Run the suite with `make test` or the sync-and-run fallback.

---

## Task 1: Topic routing

- [ ] **Step 1: Write failing tests**: a topic is created once and reused; a second event makes no second create call; each category carries its own thread id; a creation failure falls back to the general thread; unset chat id stays inert.
- [ ] **Step 2: Run to verify.**
- [ ] **Step 3: Extend** `EventType` with `topic`/`topic_name`, add `app/services/logtopics.py` (`resolve_thread_id`, `ensure_all_topics`) storing ids in `app_config`, and have `log_event` route through it.
- [ ] **Step 4: Add `/logtopics`** to the admin commands, reporting created vs existing.
- [ ] **Step 5: Run and commit.**

## Task 2: Server health, and splitting the checks

- [ ] **Step 1: Write failing tests**: disk above threshold alerts; memory above threshold alerts; a healthy host reports ok; service health reports each component.
- [ ] **Step 2: Add** `app/services/server_health.py` (disk, memory, load, uptime via stdlib only) and rename the existing checks to service health, keeping the same functions.
- [ ] **Step 3: Run and commit.**

## Task 3: Schedules

- [ ] **Step 1: Write failing tests** that the hourly pass posts both health categories to their topics, and the daily pass posts accounting.
- [ ] **Step 2: Add** the hourly health loop and the daily accounting loop beside the existing loops in `app/main.py`; route the existing backup report to its topic. Keep immediate alerts on a health state change.
- [ ] **Step 3: Run and commit.**

## Task 4: Expanded Reports

- [ ] **Step 1: Write failing tests** for each of the six new screens, the period selector on the period-based ones, and a support admin being refused.
- [ ] **Step 2: Add** `sales_report`, `signup_report` and `backup_history` to `app/services/reporting.py`, turn `adm:reports` into a menu, and add the six sub-screens reading the same functions the scheduled posts use.
- [ ] **Step 3: Full suite, then commit.**

## Task 5: Deploy and verify

- [ ] Deploy, run `/logtopics`, confirm eight topics appear in the group, and post one sample entry per category to confirm routing.

---

## Self-Review

- **Spec coverage:** §2 topics → Task 1; §3 abstraction → Task 1 Step 3; §4 cadences → Task 3; §5 health split → Task 2; §6 screens → Task 4; §7 tests → each first step.
- **Placeholder scan:** tasks are described by assertion and component, matching the previous parts' plans; the two rules most easily lost (never hardcode a thread id, never lose an entry) are carried as constraints.
- **Type consistency:** `log_event(bot, key, **values)` keeps its signature, so no call site changes; `resolve_thread_id(bot, category) -> int | None` is the only new routing entry point.
