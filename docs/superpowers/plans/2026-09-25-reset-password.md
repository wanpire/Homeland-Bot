# Reset Password Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** AloBot's once-a-month confirm-then-reset flow, on Homeland's single IBSng path, with the group guard and a row lock.

**Spec:** `docs/superpowers/specs/2026-09-25-reset-password-design.md`

## Task 1: Service
- [x] `password_change_remaining(vpn_user)` and `reset_vpn_password(session, client, vpn_user_id, telegram_id)` in `app/services/vpn_users.py`: lock the row, check owner + cooldown, run `is_homeland_group` on the live group, `change_user_password`, stamp `password_changed_at`. Typed errors for cooldown, foreign group and not found.

## Task 2: Handlers + keyboards + texts
- [x] `myservices:pw:<id>` (cooldown notice or confirm) and `myservices:pwdo:<id>` (reset and show). Bilingual texts.

## Task 3: Tests
- [x] Confirm-first, rotation, cooldown, ownership, group guard, IBSng failure.
