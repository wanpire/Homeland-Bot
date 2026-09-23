# Trial Device-First Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Trial asks protocol, then device, then sends credentials, then that device's setup, with one Tutorial/Back pair at the very end.

**Spec:** `docs/superpowers/specs/2026-09-24-trial-os-first-delivery-design.md`

## Task 1: Shared delivery message
- [x] Tests: trial text has no Tutorial-section note and no keyboard; purchase/renewal keep both.
- [x] Move the paragraph into `delivery_tutorial_note` (en/fa); append it except for trial; omit the keyboard for trial; return the message id.

## Task 2: Setup composition
- [x] `send_profile` / `send_download_links` return the message id.
- [x] Add `deliver_device_setup(protocol, platform)`: OpenVPN → profile + link; L2TP → guide + link. Returns the last message id.

## Task 3: Trial handler
- [x] Tests for the new sequence (see spec §3); update the existing trial tests to go through the device step.
- [x] `trial:protocol:<p>` shows the device picker (`trial:os:<p>:<d>`) for every protocol.
- [x] `trial:os:<p>:<d>`: gate, strip the picker keyboard, credentials, `deliver_device_setup`, attach the pair to the last message.
- [x] Keep `trial:platform:<d>` as an L2TP alias.

## Task 4
- [x] Update CLAUDE.md; run the full `make test`; commit.
