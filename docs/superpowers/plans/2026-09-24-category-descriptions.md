# Category Descriptions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Show a short description above each Buy category's plan list.

**Spec:** `docs/superpowers/specs/2026-09-24-category-descriptions-design.md`

## Task 1

- [x] **Step 1:** Add a parametrised test (3 categories × en/fa) asserting the verbatim description opens the plan-list screen.
- [x] **Step 2:** Run the full suite; expect those six to fail.
- [x] **Step 3:** Add `category_desc_{trip,scroll,stream}` to both tables in `app/i18n/texts.py`.
- [x] **Step 4:** Prefix the description in `buy_category_cb`.
- [x] **Step 5:** Run the full `make test`; commit.
