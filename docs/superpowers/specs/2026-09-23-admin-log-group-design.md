# Telegram Admin Log Group (Epic Part 5) — Design Spec

Date: 2026-09-23
Status: approved (design reviewed in chat)
Part 5 of 5.

## 1. Scope

A Telegram group that receives operational events in real time, in
English, formatted so an admin scrolling it can tell event types apart at
a glance. Six categories: new user, purchase, renewal, trial activation,
health check, backup.

Chat id comes from `Settings` (`ADMIN_LOG_CHAT_ID`), never hardcoded.

## 2. The event abstraction

One module, `app/services/adminlog.py`, owning both the format and the
sending. No caller anywhere composes a log message or calls
`bot.send_message` for logging.

```python
@dataclass(frozen=True)
class EventType:
    key: str
    emoji: str
    title: str
    fields: tuple[str, ...]   # the order fields are printed in

EVENTS: dict[str, EventType] = {...}

async def log_event(bot: Bot, key: str, **values: object) -> None
```

Adding a category later is one entry in `EVENTS` plus one call site,
which is the extensibility the request asked for.

Rendering is fixed so every entry has the same shape:

```
💰 PURCHASE
User: @someone (179494847)
Plan: 1 Month (Scroll)
Amount: $5.00
Provider: plisio
Account: ir.abc123
Time: 2026-09-23 14:02 UTC
```

Rules that make the group scannable:

- **One emoji and one upper-case title per category**, never reused
  between categories, so the eye can sort by the first line alone.
- **Fixed field order per category**, defined in `EventType.fields`, so
  the same fact is always on the same line.
- A field whose value is missing is omitted rather than printed empty.
- Every entry ends with a UTC timestamp.
- Values are HTML-escaped; the group uses the bot's HTML parse mode.

| category | emoji | title |
|---|---|---|
| new user | 🆕 | NEW USER |
| purchase | 💰 | PURCHASE |
| renewal | ♻️ | RENEWAL |
| trial | 🎁 | TRIAL |
| health ok | 💚 | HEALTH OK |
| health problem | 🔴 | HEALTH ALERT |
| backup | 💾 | BACKUP |

## 3. Never break a flow

`log_event` catches and logs every Telegram error. A misconfigured chat
id, the bot removed from the group, or Telegram being down must never
fail a purchase, a trial or a health check. Logging is observation, not
a step in any transaction.

When `admin_log_chat_id` is unset, `log_event` returns immediately, so
the feature is entirely opt-in and the test suite is unaffected.

## 4. Call sites

| event | where |
|---|---|
| new user | `app/bot/middlewares/user_tracking.py`, only when the row is newly created |
| purchase, renewal | `app/services/payments/confirmation.py`, after a successful activation |
| trial | `app/bot/handlers/trial.py`, after the account is created |
| health, backup | the periodic job below |

Purchase and renewal are logged from the confirmation path rather than
the webhook, so a payment recovered by the reconciler is logged too —
those are exactly the ones an admin most wants to see.

## 5. Health checks

A loop on the existing pattern (`run_reminder_loop`,
`run_reconcile_loop` in `app/main.py`), every 15 minutes, checking:

- **Database** — a trivial `SELECT 1`.
- **Redis** — `PING`.
- **IBSng** — `group.listGroups`, the same call the admin sync uses.
- **Plisio** — `GET /currencies/USD`, already wrapped by the client.

**Noise control is the point of this design.** AloBot's group is
described as messy; a check that announces "all ok" every 15 minutes is
how that happens. So:

- An entry is posted only when a component's state **changes**
  (ok → failing, or failing → recovered).
- Plus one daily heartbeat at most, so silence is distinguishable from a
  dead bot.

State lives in Redis (`homeland:health:<component>`), so a restart does
not re-announce everything.

## 6. Nightly backup

No backup existed: no script in the repo, no cron entry, no dumps on the
server. Confirmed in review that one should be built, since a status
report about a non-existent backup is worthless.

A job at 03:00 UTC runs `pg_dump` inside the database container, writes
`/backups/homeland-YYYYMMDD-HHMM.sql.gz` on the host through a mounted
volume, deletes dumps older than 14 days, and logs the result:

```
💾 BACKUP
Status: ok
File: homeland-20260923-0300.sql.gz
Size: 412 KB
Kept: 14 file(s)
Duration: 2.1s
Time: 2026-09-23 03:00 UTC
```

A failure logs `Status: failed` with the error, which is the case worth
waking up for. The dump runs through the existing compose service, so no
new container or credential is introduced; the database password comes
from the environment already present, never from code.

## 7. Config

```python
#: Telegram chat id of the operational log group. Negative for a
#: supergroup. Blank disables all operational logging.
admin_log_chat_id: str = ""
```

A string rather than an int so "unset" is expressible without a sentinel
number, parsed once at send time.

## 8. Tests

- Each category renders its emoji, title and fields in order.
- A missing field is omitted, not printed blank.
- Values are escaped.
- `log_event` returns silently when the chat id is unset.
- A Telegram failure is swallowed and does not propagate.
- The health loop posts on a state change and stays silent while a state
  is unchanged.
- A recovery posts.
- The backup reports success and failure shapes.
