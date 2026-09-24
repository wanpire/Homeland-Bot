# My Services Screens Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Root menu → username-labelled list → AloBot-style account menu → account-info screen with Gregorian expiry and bidi-safe credential lines.

**Spec:** `docs/superpowers/specs/2026-09-25-my-services-screens-design.md`

## Task 1: Bidi helper
- [x] `app/i18n/bidi.py`: `info_line(label, value_html, lang)` adds RLM + FSI…PDI for fa and returns plain `label: value` for en.
- [x] Unit tests: the exact characters for fa, none for en, and the marks stay outside `<code>`.

## Task 2: Service + texts
- [x] `app/services/account_view.py`: `build_account_info(session, client, vpn_user, lang) -> str` (plan, status, volume, Gregorian expiry, credentials).
- [x] New fa/en keys for the root menu, account menu, info labels and expiry variants.

## Task 3: Keyboards + handlers
- [x] Keyboards: root, list (username-first, Back → root), account menu (no renew for a trial), info (Resend Setup + Back).
- [x] Handlers: `menu:myservices` → root; `myservices:list`; `myservices:view` → account menu; `myservices:detail` → info. The Resend protocol picker's Back now points at the info screen.

## Task 4: Tests
- [x] Rewrite `test_myservices_flow.py` for the new navigation; add info-screen, list-label and bidi tests.
