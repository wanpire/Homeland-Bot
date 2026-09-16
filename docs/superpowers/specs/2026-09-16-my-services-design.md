# My Services (v1) — Design Spec

Date: 2026-09-16
Status: proposed
Parent spec: `docs/superpowers/specs/2026-09-14-homeland-bot-design.md` (§5 —
this spec implements the user-facing "view my services" screen, scoped
down per the just-completed spike's finding: no live IBSng data-usage/quota
exists on this server, so it is deliberately not shown)

## 1. Summary

Resolves the `menu:myservices` placeholder with: a list of every VPN
service a user has ever owned (trial and paid), each showing a live
status badge; a detail screen per service with plan info, live expiry,
and live-refetched credentials; and a "Resend Setup" action that reuses
the existing tutorial-delivery infrastructure to re-send the OpenVPN
profile/guide for a chosen protocol+platform.

**Spike finding this design is built on:** IBSng's `nearest_exp_date`
(read via the already-existing `IBSngClient.get_user_expiry`) is `None`
until an account's first connection starts the countdown — confirmed
live against this shared server, and matching the sibling project
AloBot's own documented experience (`app/services/reminders.py`'s
`parse_ibsng_expiry` docstring, `/Users/peyman/telegram-bot`). So status
is a four-state value, not a boolean:
- **active** — has an expiry date, and it's in the future.
- **expired** — has an expiry date, and it's in the past.
- **pending** — no expiry date yet (never connected).
- **unknown** — the IBSng lookup itself failed, or returned an
  unparseable date; never crash the screen over this, just say so.

## 2. Navigation

Callback-data namespace: `myservices:*`, matching the `menu:*`/`buy:*`/
`trial:*`/`adm:*` convention. No FSM state anywhere in this flow — every
screen is reachable from a `vpn_user_id`/`protocol_id`/`platform_id`
embedded in callback_data, the same stateless pattern Buy Subscription
and (for its protocol/platform steps) the trial flow already use.

```
menu:myservices                                   -> list screen (resolves the existing placeholder)
myservices:view:<vpn_user_id>                      -> detail screen for one service
myservices:resend:<vpn_user_id>                    -> protocol picker (Resend Setup entry point)
myservices:resend:<vpn_user_id>:protocol:<id>      -> OpenVPN: deliver directly; else platform picker
myservices:resend:<vpn_user_id>:platform:<pid>:<plid> -> deliver for L2TP + chosen platform
```

**Ownership check, every screen keyed by `vpn_user_id`:** the row must
belong to the requesting `telegram_id`, checked via a new
`get_owned_vpn_user(session, vpn_user_id, telegram_id)` service function
(§4) that returns `None` for a row that exists but belongs to someone
else — treated identically to "not found." A crafted callback naming
another customer's service id must never leak their plan or credentials.

Every screen has a Back control: list → "⬅️ Back to Menu" (`menu:root`);
detail → "⬅️ Back to List" (`menu:myservices`, re-renders the list
screen); protocol picker → "⬅️ Back to Service"
(`myservices:view:<vpn_user_id>`); platform picker → "⬅️ Back"
(`myservices:resend:<vpn_user_id>`, re-shows the protocol picker for that
same service).

## 3. List screen

```python
async def list_vpn_users_for_telegram_id(session: AsyncSession, telegram_id: int) -> list[VPNUser]:
    return list(
        (await session.execute(
            select(VPNUser).where(VPNUser.telegram_id == telegram_id).order_by(VPNUser.id)
        )).scalars().all()
    )
```

`menu:myservices` calls this, then — for each row, inside one shared
`async with IBSngClient() as client:` block (sequential calls reusing one
client, no need for concurrency given a single user's own service count
is always small) — computes its status via `get_service_status` (§4).
Zero services → an empty-state message ("🛍 You don't have any services
yet.") with Buy Subscription / Free Trial / Back to Menu buttons instead
of an empty list. Otherwise, one button per service:

```python
def myservices_list_keyboard(rows: list[tuple[VPNUser, Plan | None, str]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for vpn_user, plan, status in rows:
        name = plan.name if plan is not None else vpn_user.ibsng_group
        builder.button(text=f"{name} — {_STATUS_BADGE[status]}", callback_data=f"myservices:view:{vpn_user.id}")
    builder.button(text="⬅️ Back to Menu", callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()
```

`_STATUS_BADGE = {"active": "✅ Active", "expired": "⛔ Expired", "pending": "⏳ Pending", "unknown": "⚠️ Unknown"}`
(a handler-side constant, next to the other short display maps already
used throughout the bot, e.g. `_MEDIA_SENDERS` in `tutorial_delivery.py`).

## 4. Service status + ownership helpers (`app/services/vpn_users.py`)

```python
def parse_ibsng_expiry(raw: str) -> dt.datetime | None:
    """IBSng's nearest_exp_date reads None until an account's first
    connection starts the countdown; once set, confirmed live (on this
    shared instance, via the sibling AloBot project) as "YYYY-MM-DD HH:MM"
    (e.g. "2026-09-23 15:41"). Defensively tries that shape plus a couple
    of common fallbacks, and returns None (treat as unknown, don't crash)
    rather than guess on an unrecognized format."""
    raw = raw.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(raw, fmt).replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
    try:
        parsed = dt.datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


async def get_service_status(client: IBSngClient, username: str) -> tuple[str, dt.datetime | None]:
    """Never raises - a status check failing must never crash the screen
    showing it. Returns ("unknown", None) on any IBSng error or
    unparseable date, ("pending", None) when IBSng has no expiry yet
    (never connected), else ("active"|"expired", the parsed datetime)."""
    try:
        raw = await client.get_user_expiry(username=username)
    except IBSngError:
        return "unknown", None
    if not raw:
        return "pending", None
    expiry = parse_ibsng_expiry(raw)
    if expiry is None:
        return "unknown", None
    now = dt.datetime.now(dt.timezone.utc)
    return ("active" if expiry > now else "expired"), expiry


async def get_owned_vpn_user(session: AsyncSession, vpn_user_id: int, telegram_id: int) -> VPNUser | None:
    return (
        await session.execute(
            select(VPNUser).where(VPNUser.id == vpn_user_id, VPNUser.telegram_id == telegram_id)
        )
    ).scalar_one_or_none()
```

## 5. Detail screen

`myservices:view:<vpn_user_id>` calls `get_owned_vpn_user`; `None` (not
found OR not owned by this telegram_id — same message either way) shows
a "service not found" message with a Back-to-List button. Otherwise:

```python
async def _detail_text(session: AsyncSession, client: IBSngClient, vpn_user: VPNUser) -> str:
    plan = await get_plan(session, vpn_user.plan_id) if vpn_user.plan_id is not None else None
    name = plan.name if plan is not None else vpn_user.ibsng_group
    status, expiry = await get_service_status(client, vpn_user.ibsng_username)

    if status == "active":
        status_line = f"Status: ✅ Active until {expiry:%Y-%m-%d %H:%M} UTC"
    elif status == "expired":
        status_line = f"Status: ⛔ Expired on {expiry:%Y-%m-%d %H:%M} UTC"
    elif status == "pending":
        status_line = "Status: ⏳ Not yet activated — validity starts on first connection."
    else:
        status_line = "Status: ⚠️ Couldn't check status right now."

    password = await client.get_user_password(username=vpn_user.ibsng_username)
    password_line = f"Password: <code>{password}</code>" if password is not None else "Password: unavailable — contact support"

    return (
        f"🔑 <b>{name}</b>\n"
        f"{status_line}\n\n"
        f"Username: <code>{vpn_user.ibsng_username}</code>\n"
        f"{password_line}"
    )
```

`plan.name`/`vpn_user.ibsng_group`/`vpn_user.ibsng_username` are
catalog/generator-controlled, not user-typed — no `html.escape()` needed,
matching the precedent set in the Admin Panel and Buy Subscription final
reviews (only *typed* text needs it). Keyboard:

```python
def myservices_detail_keyboard(vpn_user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Resend Setup", callback_data=f"myservices:resend:{vpn_user_id}")
    builder.button(text="⬅️ Back to List", callback_data="menu:myservices")
    builder.adjust(1)
    return builder.as_markup()
```

## 6. Resend Setup

Mirrors the trial flow's protocol → (platform) → `deliver_setup` shape
exactly (`app/bot/handlers/trial.py`), with `vpn_user_id` threaded
through callback_data instead of relying on "the one trial account" being
unambiguous. Does **not** resend credentials — the detail screen the user
just came from already shows them; `deliver_setup` only re-sends the
profile/guide/download-link content, which is its whole job already (see
its own docstring: "does NOT send account credentials").

`myservices:resend:<vpn_user_id>` → re-validates ownership via
`get_owned_vpn_user` (same not-found handling as §5), then shows the
protocol picker (`list_protocols`, same as trial's). `myservices:resend:<vpn_user_id>:protocol:<protocol_id>`:
OpenVPN → `deliver_setup(bot, telegram_id, session, protocol_id=protocol_id, platform_id=None)`
directly, then a confirmation message with a Back-to-Service button; any
other protocol → platform picker
(`list_platforms`). `myservices:resend:<vpn_user_id>:platform:<protocol_id>:<platform_id>`
→ `deliver_setup(..., protocol_id=protocol_id, platform_id=platform_id)`,
same confirmation.

## 7. Out of scope for this spec

- Live data usage/quota — see §1's spike finding. Revisit only if a
  working IBSng report method or direct DB access is ever found.
- Any renew/cancel action from this screen — Renew Service is its own
  later item in the roadmap; My Services stays read-only + resend-setup.
- Any change to the Buy, Trial, or Admin Panel flows.
