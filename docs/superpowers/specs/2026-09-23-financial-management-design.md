# Financial Management (Epic Part 2) — Design Spec

Date: 2026-09-23
Status: approved (design reviewed in chat)
Part 2 of 5. Builds the two screens Part 1 listed as placeholders under
`adm:fin`.

## 1. Scope

Three screens under Financial:

1. **Revenue Overview** (`adm:fin:revenue`) — totals by period and by
   provider.
2. **Payments** (`adm:fin:payments`) — a searchable, paginated list with
   a per-payment detail view.
3. **Discount performance** — added to the existing Discount Codes
   screens rather than given a screen of its own, since an admin asking
   "how is SUMMER20 doing?" is already looking at SUMMER20.

Everything reads; nothing in this part mutates a payment.

## 2. What the data supports, and what it does not

Verified against the models rather than assumed:

`Payment` carries `amount_usd`, `original_amount_usd` (set only when a
discount applied), `provider`, `status`, `discount_code_id`,
`telegram_id`, `plan_id`, `purpose`, `created_at` and `resolved_at`.
That is enough for every figure below.

**Revenue counts `status == "paid"` only**, dated by `resolved_at`
(when the money actually landed), falling back to `created_at` for any
row missing it. Pending and failed rows are not revenue.

**Refunds: the status exists but nothing can set it.** `Payment.status`
allows `"refunded"`, and `app/webhook.py` treats it as terminal, but no
code path assigns it — Plisio's callback statuses map only to paid,
partially_paid and failed. So this part **reports** refunded rows if any
ever appear and does **not** build a refund action, which would be a
Plisio payout feature, not a reporting one. The screen says "0" honestly
rather than implying a capability that does not exist.

**Stripe is a placeholder in config only.** `stripe_api_key` exists and
no payment has ever carried `provider == "stripe"`. The by-provider
breakdown is driven by a `GROUP BY provider` over real rows, so Stripe
appears automatically if it ever ships, and the screen lists known
providers with zero rather than hiding them.

## 3. Revenue Overview

```
📈 Revenue Overview — Last 30 days

Paid orders:      12
Revenue:          $147.00
Average order:    $12.25
Discounts given:  $18.00

By provider
• Plisio:  12 orders · $147.00
• Stripe:  none yet

By status (all time)
• paid 12 · pending 3 · partially paid 0 · failed 9 · refunded 0
```

Period buttons: **Today · 7 days · 30 days · All time**, the same four
Part 4's reports will use. The selected period is carried in the
callback (`adm:fin:revenue:<period>`), so no FSM state is needed and a
stale keyboard stays meaningful.

"Discounts given" is `sum(original_amount_usd - amount_usd)` over paid
rows where a discount applied — the revenue deliberately forgone, which
is the number that makes discount performance interpretable.

## 4. Payments

A paginated list, newest first, eight per page to match the blocked-users
screen's `PAGE_SIZE`.

```
🧾 Payments — status: all · page 1/4

• #16 $3.00 paid · Plisio · @someone · 22 Sep
• #15 $9.00 failed · Plisio · 1029415907 · 22 Sep
...
```

Filters, each a button row that re-renders the list:

- **Status:** all · paid · pending · failed
- **Provider:** all · Plisio (and any other provider present in the data)
- **User:** a search prompt accepting `@username`, a bare username, or a
  numeric Telegram ID. This is the one FSM step in the part, mirroring
  the existing "Block a User" prompt.

Filter state travels in the callback data
(`adm:fin:payments:<status>:<provider>:<page>`) rather than FSM, for the
same reason as the period above. The user filter, being free text, is
held in FSM only while being typed and then folded into a callback as a
telegram id.

Tapping a row opens a detail view showing amount, original amount and
discount if any, provider and provider payment id, status, purpose, plan,
the IBSng username when provisioned, and both timestamps — enough to
answer "what happened to this order?" without a database query. It links
out to the invoice URL when one exists.

## 5. Discount performance

The existing discount detail screen (`adm:discounts:view:<id>`) gains:

```
Performance
• Used: 4 of 10
• Revenue from this code: $34.00
• Discount given: $6.00
```

Computed over paid payments carrying that `discount_code_id`. `used_count`
on the code and the payment count can legitimately differ — the counter
increments at activation while the payment rows are the audit trail — so
both are shown rather than one being presented as the other.

## 6. Permissions

Everything here is sales and above, inheriting `adm:fin`. The Payments
detail view shows a customer's Telegram id and username, which support
admins already see elsewhere, but revenue figures stay sales-and-above.

## 7. Shape

- `app/services/reporting.py` (new) — pure query functions returning
  dataclasses: `revenue_summary(session, period)`, `payment_page(session,
  filters, page)`, `payment_detail(session, payment_id)`,
  `discount_performance(session, discount_code_id)`. No aiogram imports;
  Part 4's reports will reuse the period helper.
- `app/bot/keyboards/financial.py` (new) — period, filter and pagination
  keyboards.
- `app/bot/handlers/financial.py` (new router, `adm:fin:*`) — replaces
  Part 1's placeholder handler in `admin.py`.
- Registered before `admin_fallback`, like every other `adm:*` router.

Periods live in one place as a `PERIODS` mapping of key to label and
timedelta, so Part 4 cannot drift from Part 2's definitions.

## 8. Tests

- Revenue totals only paid rows; pending and failed are excluded.
- Period filtering is inclusive of the boundary and excludes older rows.
- By-provider grouping reflects the data, and a provider with no rows
  still renders.
- Discounts given equals original minus charged.
- The payment list paginates, and each filter narrows the set.
- User search accepts `@username`, bare username and a numeric id.
- Payment detail renders a discounted payment and an undiscounted one.
- Discount performance counts only paid payments for that code.
- A support admin is refused every screen.
