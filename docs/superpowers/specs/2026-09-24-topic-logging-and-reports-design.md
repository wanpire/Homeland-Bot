# Topic-Structured Logging and Expanded Reports — Design Spec

Date: 2026-09-24
Status: approved (design reviewed in chat)
Covers Parts 1–3 of the request as one feature: they share the log-event
abstraction and the query layer. Part 4 shipped separately.
Supersedes the routing half of
`docs/superpowers/specs/2026-09-23-admin-log-group-design.md`.

## 1. Confirmed before designing

The request made this a precondition, so it was checked first:

- `-1004466777356` is a **supergroup with `is_forum: True`**, titled
  "HomelandBot Reports". The chat id is unchanged by the forum
  conversion, so nothing about addressing the group changes.
- The bot is an **administrator with `can_manage_topics: True`**, so
  `createForumTopic` will succeed.

Part 3's prerequisites also already exist, from the previous epic:

- **Backups**: `app/services/backup.py` runs a nightly `pg_dump`,
  gzipped to `/backups` with 14-day retention, and one real dump has
  run on the server.
- **Health**: `app/services/health.py` checks the database, Redis,
  IBSng and Plisio.

Nothing here is fabricated for want of data.

## 2. Topics

Eight, one per category:

| category key | topic name | what lands there |
|---|---|---|
| `new_user` | 🆕 New Users | first interaction |
| `purchase` | 💰 Purchases | paid orders |
| `renewal` | ♻️ Renewals | renewals |
| `trial` | 🎁 Trials | trial activations |
| `backup` | 💾 Backups | nightly dump results |
| `server_health` | 🖥 Server Health | host: disk, memory, load |
| `service_health` | 🩺 Service Health | IBSng, Plisio, database, Redis |
| `accounting` | 📊 Accounting | daily revenue summary |

Thread ids are **discovered, never hardcoded**. On first use a topic is
created with `createForumTopic` and its `message_thread_id` is stored in
the existing `app_config` key/value table under
`log_topic:<category>` — the same store the mandatory-channel and
support-contact settings already use. A `/logtopics` admin command
re-runs the setup, reporting which topics existed and which were
created, so a group rebuilt from scratch is one command away from
working.

If topic creation fails, or the group is not a forum, the entry is sent
to the group's general thread instead. A log entry must never be lost
because its filing cabinet is missing.

## 3. The event abstraction

`app/services/adminlog.py` keeps its shape — `EventType` with a fixed
emoji, title and field order, `render_event`, `log_event` — and gains:

```python
@dataclass(frozen=True)
class EventType:
    key: str
    emoji: str
    title: str
    fields: tuple[str, ...]
    topic: str          # new: which topic this category files under
    topic_name: str     # new: the topic's display name
```

`log_event` resolves the thread id for the event's topic (creating it on
demand), then sends with `message_thread_id`. Everything else about it
is unchanged: it never raises, and it returns immediately when
`ADMIN_LOG_CHAT_ID` is blank.

Adding a category stays one `EVENTS` entry plus one call site.

## 4. Real-time vs scheduled

| category | cadence | trigger |
|---|---|---|
| new user, purchase, renewal, trial | real time | the existing call sites, unchanged |
| server health, service health | hourly | new loop |
| backup | nightly | existing backup loop, now routed to its topic |
| accounting | daily | new loop |

**The hourly health post replaces the previous state-change-only rule**,
which was designed for a single shared group where "all ok" every
fifteen minutes was noise. With a dedicated topic that reasoning
inverts: an hourly heartbeat in a topic nobody has to read is
reassurance, and its absence is itself a signal. Failures still post
immediately on the state change, so a problem does not wait up to an
hour.

## 5. Server health vs service health

The request separates these, and they are genuinely different questions:

- **Server health** — the host: disk usage of the filesystem holding the
  database and backups, memory, load average, and how long the process
  has been up. Read from `shutil.disk_usage`, `/proc/meminfo` and
  `os.getloadavg`, so no new dependency is added.
- **Service health** — the moving parts: database, Redis, IBSng (with
  its Homeland group count) and Plisio. This is today's `check_all`,
  renamed for clarity.

Thresholds: disk above 85% used or memory above 90% used posts an alert
rather than an ok. Those are the two that actually page someone.

## 6. Expanded Reports screen

`adm:reports` becomes a menu rather than a single page:

```
📊 Reports
├── 📈 Overview        (today's screen, unchanged)   adm:reports:overview
├── 🆕 Signups         adm:reports:signups
├── 💰 Sales           adm:reports:sales
├── 📊 Accounting      adm:reports:accounting
├── 🩺 Service Health  adm:reports:service
├── 🖥 Server Health   adm:reports:server
├── 💾 Backups         adm:reports:backups
└── ⬅️ Back
```

The period selector stays on the period-based screens (Overview,
Signups, Sales, Accounting) and is absent from the three that describe
"right now" (both health screens) or a file list (Backups).

**One query layer.** Every screen and every scheduled message reads the
same functions in `app/services/reporting.py` and the two health
modules. The accounting summary an admin taps and the one posted at
08:00 are the same call, so they cannot disagree.

New query functions: `sales_report(session, period)` (orders, revenue,
by plan, by provider, average), `signup_report(session, period)`
(new users, how many bought, conversion), `backup_history(limit)`
(recent dumps with size and age, read from the backup directory).

## 7. Tests

- Topic ids are created once, stored, and reused; a second call makes no
  second `createForumTopic`.
- A failed topic creation falls back to the general thread rather than
  dropping the entry.
- Each category routes to its own thread id.
- `/logtopics` reports created and existing topics.
- Server health flags a full disk and high memory.
- Service health reports each component.
- Hourly and daily loops post to the right topics.
- Each new report screen renders, and period-based ones respond to the
  selector.
- A support admin is refused every new screen.
