# Order Delivery Message, Username Prefix and IBSng Credit — Design Spec

Date: 2026-09-22
Status: approved (design reviewed in chat)
Related: `docs/superpowers/specs/2026-09-16-crypto-payment-design.md` §9
(the confirmation message this replaces).

## 1. Summary

Three changes to what a buyer receives once a payment is confirmed:

1. The one-line confirmation ("🎉 Payment confirmed! Your service
   (`hl.d6jxur`) has been activated.") becomes a full delivery message
   carrying the plan, duration, volume and tap-to-copy credentials, with
   buttons to the Tutorials section and the main menu.
2. Generated IBSng usernames change prefix from `hl.` to `ir.`.
3. Unlimited plans are provisioned with IBSng credit **100** instead of
   10.

Point 3 is narrower than the original request, by the product owner's
decision in review: the request was a flat 100 for every account, which
would have removed the per-user data cap that metered plans rely on. A
5 GB plan is provisioned today with `credit=5120`; under a flat 100 that
buyer's own credit would no longer cap them and quota would rest
entirely on the IBSng group policy. Metered plans therefore keep passing
their data cap, and only the unlimited sentinel path changes.

## 2. The message

One key per language, `order_delivered`, rendered with the bot's
existing HTML parse mode. Field labels are bold, credentials are
`<code>` spans so Telegram offers tap-to-copy on each one individually.

English:

```
🎉 Your order has been placed successfully.

<b>Plan:</b> {plan}
<b>Duration:</b> {days} days from first connection
<b>Volume:</b> {volume}

<b>Username:</b> <code>{username}</code>
<b>Password:</b> <code>{password}</code>

Setup instructions and connection details for different platforms and
protocols are available in the Tutorial section of the main menu.
```

Persian mirrors it exactly, with the labels پلن خریداری‌شده / مدت زمان
استفاده / حجم / یوزرنیم / پسورد and the closing sentence given in the
request.

A second key, `order_delivered_no_password`, is identical but omits the
password line and closes with the existing "contact support" wording.
It is used only when the password cannot be recovered (§4).

Values:

| placeholder | source |
|---|---|
| `{plan}` | `plan_display_name(plan, lang)` from `payment.plan_id` |
| `{days}` | `plan.duration_days` |
| `{volume}` | `format_data_cap(payment.data_cap_mb, lang)` — the **snapshot** on the payment, not the plan's current value, matching the project's existing rule that an admin editing the catalog mid-payment cannot change what was sold |
| `{username}` | the username `activate_finished_payment` returns |
| `{password}` | §4 |

`format_data_cap` already renders `0` as "نامحدود"/"Unlimited" and
otherwise as GB or MB, so unlimited and metered plans both come out
right with no new branching.

Keyboard, both languages, reusing the existing destinations rather than
new callbacks:

- 📘 آموزش / 📘 Tutorial → `menu:tutorials`
- 🔙 بازگشت به منوی اصلی / 🔙 Back to Main Menu → `menu:root`

## 3. Where it is sent

`app/services/payments/confirmation.py`'s `confirm_paid_payment`, the
single path both the callback and the reconciler use. The old
`payment_confirmed` / `action_activated` / `action_renewed` keys are
removed.

Renewals send the same message, by the product owner's decision in
review: the buyer renewed an existing account and re-showing its
credentials is useful, and one delivery format is easier to keep correct
than two.

## 4. Where the password comes from

- **Purchase:** `payment.ibsng_password`, generated when the payment row
  was created and already stored on it.
- **Renewal:** the payment carries no password, because the account
  keeps the one it has. It is read back with
  `IBSngClient.get_user_password`, exactly as the trial flow's
  `_send_trial_credentials` already does.

If the lookup returns nothing or IBSng errors, the message falls back to
`order_delivered_no_password`. The service is provisioned either way, so
a missing password must never look like a failed order.

## 5. Username prefix

`_USERNAME_PREFIX` in `app/services/vpn_users.py` becomes `"ir."`. It is
already a single named constant used only by `generate_vpn_credentials`,
so this is a one-line change. Existing accounts keep their `hl.` names;
nothing rewrites them, and nothing in the code matches on the prefix.

## 6. IBSng credit

`_UNLIMITED_IBSNG_CREDIT` is renamed `UNLIMITED_PLAN_IBSNG_CREDIT` and
raised from 10 to 100, with its comment updated to record that the value
is a product decision rather than an IBSng requirement. The mapping in
`create_vpn_user` is otherwise unchanged:

```python
ibsng_credit = UNLIMITED_PLAN_IBSNG_CREDIT if data_cap_mb == 0 else data_cap_mb
```

## 7. Tests

- `tests/functional/test_payment_recovery.py` / `test_webhook.py`:
  assert the delivered message carries the plan name, duration, volume,
  and both credentials in `<code>` spans, and that the keyboard offers
  the Tutorials and main-menu buttons. One test per language.
- A renewal test asserting the password is read back from IBSng, and one
  asserting the no-password fallback when it cannot be.
- `tests/functional/test_trial_flow.py` and any test asserting a
  generated username: expect the `ir.` prefix.
- A provisioning test asserting `create_user` receives `credit=100` for
  an unlimited plan and the plan's own cap for a metered one.
- `tests/functional/test_i18n.py`: the key-set parity and count checks.
