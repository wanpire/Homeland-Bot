# Homeland Bot

Telegram bot selling reverse VPN (Iran-based IP addresses) in USD to
Iranian customers living outside Iran. Backend provisioning/accounting is
IBSng (same server as the sibling AloBot project, separate ISP/groups).

## Status

This is the bootstrap/foundation slice: repo scaffold, config, DB/Redis,
the ported IBSng client, the 4-plan catalog, and a main menu that shows
all 4 buttons with "coming soon" placeholders. Buy/Renew/My Services/
Tutorial & Support/Admin Panel are implemented in follow-up plans under
`docs/superpowers/plans/`.

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
