---
name: ibsng-xmlrpc-integration
description: Homeland's IBSng XML-RPC integration patterns - confirmed server quirks, the shared-instance group-namespace isolation rule, and the pre-check-before-external-call idempotency pattern. Use when touching app/services/ibsng/client.py, app/services/groups.py, app/services/vpn_users.py, or any code that creates/renews/modifies an IBSng account or reads IBSng groups.
---

# IBSng XML-RPC Integration (Homeland)

`app/services/ibsng/client.py`'s `IBSngClient` is the **only** place in this
codebase allowed to call the IBSng API. Every handler and service goes
through it - never construct an `xmlrpc.client.ServerProxy` anywhere else.

## Transport and auth

- Plain XML-RPC over HTTP(S) to `IBSNG_BASE_URL` (IBSng Free 1.24, default
  port 1235).
- There is **no session/token concept** in this edition. Every single call
  re-sends the full auth block merged into its params:
  `auth_type: "ADMIN"`, `auth_name`, `auth_pass`, `auth_remoteaddr`.
- All calls run through `asyncio.to_thread(...)` since `xmlrpc.client` is
  synchronous - never call the proxy directly from an `async def` without
  that wrapper.
- A `xmlrpc.client.Fault` from `getUserInfo` means "user does not exist",
  not a real error - handled by `_get_user_info_or_none`. `ProtocolError`/
  `OSError` (can't reach the server at all) get wrapped in `IBSngError`.

## Confirmed real-server quirks (do not re-derive these - they cost real
debugging time against production the first time)

These were confirmed against the actual IBSng Free 1.24 server this
project (and its sibling AloBot) runs against. If IBSng's behavior ever
looks like it contradicts one of these, re-verify against the live
server rather than trusting third-party/commercial IBSng docs - the
commercial docs describe a different attrs shape than what this server
actually accepts.

- `group.listGroups` returns a **plain list of group name strings** (not
  objects).
- `user.doesUserExists` **is not a valid handler method** on this server.
  Existence checks always go through `user.getUserInfo` and treat a Fault
  as "does not exist" - see `_get_user_info_or_none`.
- Creating a user is a **two-step process**:
  1. `user.addNewUsers(count=1, isp_name, owner_name, group_name, credit,
     credit_comment)` -> returns `[user_id]`. `owner_name` is **required**
     (defaults to `IBSNG_USERNAME` if not set separately).
  2. `user.updateUserAttrs(user_id, attrs={...6 flat keys...},
     to_del_attrs=[])` to actually set the username/password. The attrs
     shape is **flat** - `normal_username`, `normal_generate_password`,
     `normal_generate_password_len`, `normal_password`, `normal_save`,
     `normal_save_usernames` - not the nested `normal_user_spec` object
     the commercial IBSng docs describe. The nested shape is silently
     ignored by this server; you'll get no error, just a user with no
     credentials set.
- `user.getUserInfo`'s response nests everything: the stored password
  (`normal_password`) and expiry (`nearest_exp_date`) live under `attrs`,
  the group name lives under `basic_info` - not flat on the top-level
  response. See `_split_user_info` for how this codebase unwraps it
  (the response shape itself varies - sometimes keyed by `user_id`,
  sometimes containing `basic_info` directly - `_split_user_info` handles
  both).
- Changing a user's group: `user.updateUserAttrs` with
  `attrs={"group_name": new_name}`. There is no `group_id` field that
  works - passing one is silently ignored.
- Locking a user: `user.updateUserAttrs` with `attrs={"lock": bool}`.
- Renewing a user (resetting validity so it restarts from next
  connection): `user.updateUserAttrs` with `to_del_attrs=["first_login"]`
  and an empty `attrs={}` - this is the XML-RPC equivalent of IBSng's
  admin-panel "reset first login" button. Deleting an already-unset
  attribute is a no-op, so this is naturally idempotent - safe to retry.
- **`user_balance.getUserBalanceInfoByUserID` is confirmed DEAD on this
  server** ("Handler --user_balance-- not found", reproduced twice in
  AloBot's history on the same shared instance). Never call it, including
  for a future quota/usage-reading feature - that feature must probe for
  a working alternative first (another `user_balance.*` method, a field
  already on `getUserInfo`'s `attrs`, or an `accounting.*` handler) and
  document whatever is confirmed to work in `client.py`'s module
  docstring, the same way every other quirk here is documented.

## Shared-instance group-namespace isolation (non-negotiable)

This IBSng server is **shared with a sibling bot project** (AloBot, a
separate Telegram bot selling VPN the opposite direction, in Toman
instead of USD) that has its own groups on the same instance.
`group.listGroups` returns everyone's groups undifferentiated - Homeland's
and AloBot's mixed together.

The only thing preventing Homeland from reading, syncing, or offering an
AloBot group is the allowlist filter in `app/services/groups.py`:

```python
_ALLOWED_GROUP_PREFIXES = ("2W-", "1M-", "2M-", "3M-", "Trial-")

def _is_homeland_group(name: str) -> bool:
    return name.startswith(_ALLOWED_GROUP_PREFIXES) and "Iran" in name
```

Every real Homeland group name matches this pattern; no AloBot group name
does. `sync_groups()` is the **only** code path allowed to populate the
local `groups` table, and it always applies this filter before upserting
anything.

**Rule:** any new code that calls `IBSngClient.list_groups()` directly -
bypassing `sync_groups()` - must apply the identical filter before
presenting a group name to anyone (an admin picker, a plan editor,
anything). Never assume a name returned by `list_groups()` belongs to
Homeland just because it's on this server.

## Pre-check-before-external-call pattern

IBSng account creation is called against a **shared production
instance** - an orphaned account there is a real, visible, hard-to-clean-up
mistake, not a harmless retry. The rule this codebase follows everywhere
it creates or claims a resource against IBSng:

**Check every local DB constraint that would reject the write BEFORE
calling IBSng - never after.**

`app/services/vpn_users.py`'s `create_vpn_user` is the canonical example:

```python
existing = await session.execute(select(VPNUser).where(VPNUser.ibsng_username == username))
if existing.scalar_one_or_none() is not None:
    raise VPNUsernameTakenError(...)

# Must come BEFORE the IBSng call: a DB constraint failure AFTER
# provisioning a real IBSng account leaves it orphaned with no local
# row pointing at it.
if is_trial and await has_used_trial(session, telegram_id):
    raise TrialAlreadyUsedError(...)

await client.create_user(...)   # the external call comes LAST
```

A real production bug this pattern was written to prevent: a replayed or
double-tapped Telegram callback that skipped this ordering created a real
IBSng account on every retry, because the trial-already-used check only
happened after the local insert failed - by which point the account
already existed on the shared instance. When adding any new IBSng-backed
create/claim flow (renew-by-username, a future Buy flow, etc.), work out
every local constraint that could reject the request and check all of
them before the first IBSng call, not just the cheapest one.

## Where things live

- `app/services/ibsng/client.py` - the client itself, all IBSng calls.
- `app/services/ibsng/exceptions.py` - `IBSngError`, `IBSngUserExistsError`,
  `IBSngUserNotFoundError`.
- `app/services/groups.py` - the namespace-filtered local group cache.
- `app/services/vpn_users.py` - the account creation/renewal path that
  demonstrates the pre-check pattern.
