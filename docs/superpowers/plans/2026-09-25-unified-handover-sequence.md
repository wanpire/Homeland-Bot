# Unified Handover Sequence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Trial, purchase and renewal all run one sequence: device, then protocol (skipped when only one fits, e.g. Android → OpenVPN), then credentials, then that device's setup, then one Tutorial/Back pair.

**Spec:** `docs/superpowers/specs/2026-09-25-unified-handover-sequence-design.md`

## Task 1: Compatibility rule
- [x] `protocols_for_platform(platform, protocols)` in `app/services/tutorials.py`, built on `is_protocol_valid_for_platform`.
- [x] Unit tests: Android drops L2TP; other devices keep every protocol.

## Task 2: Shared delivery message
- [x] `build_delivery_text` never appends a Tutorial note; `send_account_delivery` never attaches a keyboard. Delete `delivery_tutorial_note` (en/fa).
- [x] Update `test_delivery_message.py`.

## Task 3: Handover service + keyboards + router
- [x] `app/services/handover.py`: `HandoverAccount`, `load_handover_account` (trial / paid, with ownership checks and password recovery), `send_handover_prompt` (paid), `deliver_handover` (gate → credentials → `deliver_device_setup` → pair).
- [x] `app/bot/keyboards/handover.py`: device picker (optional Back), protocol picker (Back → device).
- [x] `app/bot/handlers/handover.py`: `ho:<src>:<ref>:os:<d>`, `ho:<src>:<ref>:pr:<d>:<p>`, `ho:<src>:<ref>:back`; disarm before delivering. Register it in `app/main.py`.

## Task 4: Trial on the shared path
- [x] `trial:confirm` → device picker (`ho:t:<vpn_user_id>`). Remove the trial's own credential and delivery code.
- [x] Legacy aliases: `trial:os`, `trial:platform` deliver; `trial:protocol`, `trial:back_to_protocol` open the device picker.
- [x] Rewrite `test_trial_flow.py` for the device-first order, the Android skip, and the legacy aliases.

## Task 5: Purchase / renewal on the shared path
- [x] `confirmation.py` sends only the payment-received device prompt (`ho:p:<payment_id>`).
- [x] Update the webhook, payment-recovery and renewal tests to tap through the sequence; add a sequence test, an Android test and an ownership test for paid orders, plus a "both flows call `deliver_handover`" test.

## Task 6
- [x] Update CLAUDE.md; run the FULL `make test` (692 passed).
- [ ] Commit and deploy (awaiting go-ahead).
