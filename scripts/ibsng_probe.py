#!/usr/bin/env python3
"""One-off diagnostic script for inspecting real IBSng data over
XML-RPC. Reads IBSNG_BASE_URL/IBSNG_USERNAME/etc. from the environment
(.env) - no hostname is ever hardcoded here.

Usage (run inside the bot container, or a venv with .env loaded):
  python scripts/ibsng_probe.py user <username>
  python scripts/ibsng_probe.py groups
  python scripts/ibsng_probe.py raw <handler.method> <json-payload>
"""

import asyncio
import json
import sys

from app.services.ibsng.client import IBSngClient


async def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)

    command = sys.argv[1]
    async with IBSngClient() as client:
        if command == "user" and len(sys.argv) == 3:
            result = await client.get_user_info(username=sys.argv[2])
        elif command == "groups":
            result = await client.list_groups()
        elif command == "raw" and len(sys.argv) == 4:
            # Free-form escape hatch for probing candidate handlers the
            # typed client doesn't wrap yet (e.g. quota/traffic data -
            # see docs/superpowers/specs/2026-09-14-homeland-bot-design.md §5).
            method_name, payload_json = sys.argv[2], sys.argv[3]
            result = await client._call(method_name, **json.loads(payload_json))  # noqa: SLF001
        else:
            print(__doc__)
            raise SystemExit(1)

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
