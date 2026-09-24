# Change Ownership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Owner offers an account to another bot user; it moves only when that user accepts.

**Spec:** `docs/superpowers/specs/2026-09-25-change-ownership-design.md`

## Task 1: Model + migration
- [x] `OwnershipTransfer` model; migration `0011_ownership_transfers`.

## Task 2: Service `app/services/ownership.py`
- [x] `resolve_recipient`, `create_transfer` (supersedes older pending ones), `accept_transfer` / `decline_transfer` / `cancel_transfer` with row locks, the 24h expiry and an ownership re-check; accept clears `password_changed_at`.
- [x] adminlog `OWNERSHIP` event, "🔑 Accounts" topic.

## Task 3: Handlers
- [x] `app/bot/handlers/ownership.py`: `myservices:xfer:<id>` (FSM prompt), recipient message, `myservices:xferask:<id>:<to>`, `xfer:accept|decline|cancel:<t>`. The account menu (`myservices:view`) clears the FSM state.

## Task 4: Tests, docs, full suite
- [x] Every case in spec §5. Update CLAUDE.md. Run the FULL `make test` (733 passed).
- [ ] Send the owner the sample screens for the bidi check.
