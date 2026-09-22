# Shared Account Delivery Message — Design Spec

Date: 2026-09-23
Status: approved (design reviewed in chat)
Supersedes the delivery half of
`docs/superpowers/specs/2026-09-22-order-delivery-message-design.md`,
which introduced the message for paid orders only.

## 1. Summary

Three flows hand a customer a working account: a new purchase, a
renewal, and a free trial. Each currently writes its own message. They
converge on one template, with only the headline differing.

Purchases and renewals already share
`app/services/payments/confirmation.py`'s delivery message; the trial
has its own `trial_ready` text and its own sending code in
`app/bot/handlers/trial.py`. After this change all three call one
function and there is a single body per language to keep correct.

## 2. The message

```
{headline}

<b>{plan_label}:</b> {plan}
<b>{duration_label}:</b> {days} {day_word} from first connection
<b>{volume_label}:</b> {volume}

<b>{username_label}:</b> <code>{username}</code>
<b>{password_label}:</b> <code>{password}</code>

{tutorial_note}
```

Rendered with the bot's HTML parse mode: labels bold, each credential in
its own `<code>` span so Telegram offers tap-to-copy on each separately.

Headline keys, one per flow:

| flow | en | fa |
|---|---|---|
| purchase | 🎉 Your order has been placed successfully. | 🎉 سفارش شما با موفقیت ثبت شد. |
| renewal | 🎉 Your renewal was successful. | 🎉 تمدید شما با موفقیت انجام شد. |
| trial | 🎉 Your trial service is ready. | 🎉 سرویس تست شما آماده است. |

The renewal wording was confirmed in review rather than chosen silently.

Body keys: `delivery_body` and `delivery_body_no_password`, the latter
replacing the password line with a contact-support note. Two keys rather
than a conditional line, so each language's full text is readable in one
piece.

**Plural.** English renders "1 day" and "30 days"; the day word is a
separate key pair (`day_singular`, `day_plural`) chosen by count. Persian
uses روز for both, since it does not inflect. Confirmed in review: the
trial's old "valid for 24 hours" wording is dropped in favour of the
shared line, which says the same thing.

## 3. The one function

`app/services/delivery.py` (new):

```python
PURCHASE = "purchase"
RENEWAL = "renewal"
TRIAL = "trial"

_HEADLINE_KEYS = {
    PURCHASE: "delivery_headline_purchase",
    RENEWAL: "delivery_headline_renewal",
    TRIAL: "delivery_headline_trial",
}

async def send_account_delivery(
    bot: Bot,
    telegram_id: int,
    *,
    kind: str,                 # PURCHASE | RENEWAL | TRIAL
    plan: Plan | None,
    data_cap_mb: int,
    username: str,
    password: str | None,
    lang: str,
) -> None
```

It builds headline + body, and sends with
`order_delivered_keyboard(lang)` (Tutorial → `menu:tutorials`, Back →
`menu:root`, both existing destinations). A blocked bot is logged and
swallowed: the account is provisioned either way.

`data_cap_mb` is passed separately from `plan` on purpose. For a paid
order it is the **snapshot on the payment**, so an admin editing the
catalog mid-purchase cannot change what that buyer was sold; for a trial
it is the trial plan's own value. The function never re-derives it.

## 4. Callers

- **Purchase and renewal** —
  `app/services/payments/confirmation.py` keeps resolving plan, data cap
  and password, then calls `send_account_delivery` with `kind=PURCHASE`
  or `RENEWAL` from `payment.purpose`. Its private message-building
  helper goes away.
- **Trial** — `app/bot/handlers/trial.py`'s `_send_trial_credentials`
  shrinks to: find the just-created `VPNUser`, read the password back
  from IBSng, load the trial plan, call `send_account_delivery` with
  `kind=TRIAL`.

## 5. What a trial resolves to

Verified against the seeded catalog rather than assumed: migration
`0004_correct_catalog_to_real_groups.py` seeds
`("Trial", "trial", 1, 1024, "0.00", "Trial-Iran", 0)`, so a trial is a
real `Plan` row like any other.

| field | value |
|---|---|
| plan | `plan_display_name` → "Trial" / "تست رایگان" |
| duration | 1 → "1 day" / "۱ روز" |
| volume | `format_data_cap(1024)` → "1 GB" |

The trial handler loads that row through the existing
`list_plans(session, category="trial")` it already uses, so the values
come from the catalog and follow an admin editing it.

## 6. Password sourcing (unchanged behaviour)

- Purchase: `payment.ibsng_password`.
- Renewal and trial: read back with `IBSngClient.get_user_password`,
  which both already do.
- Unreadable: `delivery_body_no_password`. The trial's dedicated
  `trial_credentials_unavailable` message is removed, since the shared
  fallback already says the account exists and to contact support, and
  it now also shows the username, which the old message did not.

## 7. Removed keys

`trial_ready`, `trial_credentials_unavailable`, `order_delivered`,
`order_delivered_no_password`.

## 8. Tests

- One test per flow asserting the same body and the same two buttons,
  with that flow's headline.
- Persian rendering for at least one flow per language path.
- Trial fields resolve from the trial plan: "Trial", "1 day", "1 GB".
- "1 day" singular and "30 days" plural.
- No-password fallback on each of the three paths.
- Credentials in separate `<code>` spans.
