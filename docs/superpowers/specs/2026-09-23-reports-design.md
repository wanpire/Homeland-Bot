# Reports (Epic Part 4) — Design Spec

Date: 2026-09-23
Status: approved (design reviewed in chat)
Part 4 of 5. Builds on Part 2's `app/services/reporting.py`.

## 1. Scope

One screen, `adm:reports`, with the same four periods Financial uses,
covering:

- new signups in the period
- active vs expired accounts
- revenue in the period
- trial-to-paid conversion
- top plans by sales

Sales and above, inheriting the tier Part 1 gave the menu entry.

## 2. The screen

```
📊 Reports — Last 30 days

Signups: 14        (all time: 62)
Revenue: $147.00 from 12 paid order(s)

Accounts
• Active: 9 · Expired: 3 · Pending: 1
  (live status of the 20 newest of 41 accounts)

Trial conversion
• Trials started: 23 · went on to pay: 6 → 26.1%

Top plans (paid orders in period)
1. 1 Month (Scroll) — 6 · $30.00
2. 2 Weeks (Trip)   — 4 · $12.00
3. 1 Month (Stream) — 2 · $36.00
```

Periods reuse `PERIODS` and `period_start` rather than redefining them,
so a figure here and the same figure under Financial can never disagree.
Revenue reuses `revenue_summary` outright.

## 3. Where each number comes from, and its honest limit

**Signups** — `BotUser.first_seen_at` within the period. This counts
people who started the bot, not buyers.

**Accounts: active vs expired needs IBSng.** As Part 3 established,
`VPNUser.expires_at` is never written, so the only truth is
`get_service_status`, one round trip per account. Checking every account
would make this screen's cost grow without limit, so it checks the **20
newest** and states both numbers: how many it checked and how many exist.
A report that silently sampled would be worse than one that says it
sampled.

**Revenue** — `revenue_summary(session, period)`, unchanged from Part 2:
paid rows only, dated by `resolved_at` falling back to `created_at`.

**Trial conversion** — trials started is the count of distinct
`telegram_id` with a trial `VPNUser` created in the period; converted is
how many of those same people have at least one paid `Payment` **at any
time**, not only within the period, because a trial taken on the 30th
and paid on the 2nd is still a conversion. The denominator is therefore
period-scoped and the numerator is not, which the label states.

**Top plans** — paid payments in the period grouped by `plan_id`, with
count and revenue, top five, resolved to plan names.

## 4. Shape

`app/services/reporting.py` gains `signup_count`, `account_breakdown`,
`trial_conversion` and `top_plans`, each a plain query function beside
the Part 2 ones. `app/bot/handlers/admin.py`'s Part 1 placeholder is
replaced by a handler in a new `app/bot/handlers/reports.py` owning
`adm:reports[:<period>]`, with its keyboard in
`app/bot/keyboards/reports.py`.

`account_breakdown` takes the IBSng client from its caller, as
`user_overview` does, so a test hands over the fake.

## 5. Tests

- Signups count only the period; all-time is reported alongside.
- Account breakdown counts each live status and reports checked vs total
  when it samples.
- An IBSng outage yields "unknown" counts rather than raising.
- Conversion counts a trial user who paid later, and divides by trials
  in the period; zero trials yields 0% rather than a division error.
- Top plans ranks by paid orders and excludes pending and failed.
- Every period renders.
- A support admin is refused.
