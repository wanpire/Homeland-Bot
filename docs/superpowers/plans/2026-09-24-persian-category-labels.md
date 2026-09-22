# Persian Category Labels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Rename three Persian category labels; touch nothing else.

**Spec:** `docs/superpowers/specs/2026-09-24-persian-category-labels-design.md`

## Global Constraints

- Display strings only. The slugs `scroll`, `stream`, `trip` key the database and must not change.
- English labels stay as they are; admin screens stay English-only.

## Task 1

- [ ] **Step 1:** Add a test asserting the three Persian labels and the three English ones.
- [ ] **Step 2:** Run it; expect failure on the Persian values.
- [ ] **Step 3:** Edit the three `fa` entries in `app/i18n/texts.py`.
- [ ] **Step 4:** Run the full suite; commit.
- [ ] **Step 5:** Deploy and check the Buy screen in Persian.

## Self-Review

- **Spec coverage:** §1 → Task 1 Step 3; §2 → the constraints; §3 → Step 1.
- **Placeholder scan:** none; the change is three lines.
- **Type consistency:** no signatures involved.
