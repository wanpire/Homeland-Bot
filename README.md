# Homeland Bot

Telegram bot selling reverse VPN (Iran-based IP addresses) in USD to
Iranian customers living outside Iran. Backend provisioning/accounting is
IBSng, on the **same shared instance** as the sibling AloBot project
(separate ISP/groups) - see "Shared IBSng instance" below before touching
anything group-related.

## Status

This is the bootstrap/foundation slice: repo scaffold, config, DB/Redis,
the ported IBSng client, the catalog (Scroll/Stream/Trial, 7 plans), and
a main menu that shows all 5 buttons with "coming soon" placeholders.
Buy/Renew/My Services/Free Trial/Tutorial & Support/Admin Panel are
implemented in follow-up plans under `docs/superpowers/plans/`.

## Shared IBSng instance

Homeland and AloBot are two separate Telegram bot products that
provision accounts on the **same** IBSng server. Homeland's own groups
all match the pattern `(2W-|1M-|2M-|3M-|Trial-)....Iran...` (spec §4,
§14) - `app/services/groups.py`'s `sync_groups()` filters to exactly
this pattern before ever touching the local `groups` table, so AloBot's
groups (Normal/Prime/Junior tiers) are never read, listed, or referenced
by this bot. Any new code that lists IBSng groups must apply the same
filter. Homeland runs on its own dedicated server (separate from
AloBot's host) and reaches this shared IBSng instance over the network -
confirm `IBSNG_BASE_URL` and firewall rules before deploying (spec §11).

## Setup

```bash
make setup    # interactive .env generator
make up       # docker compose up -d --build
make migrate  # apply database migrations
```

## Testing

Fully isolated stack (own Postgres/Redis, in-process fake IBSng XML-RPC
server and fake Telegram session - nothing reaches production or real
Telegram):

```bash
make test
```

## Design docs

- `docs/superpowers/specs/2026-09-14-homeland-bot-design.md` - full design
- `docs/superpowers/plans/2026-09-14-homeland-bootstrap.md` - this slice's plan
