"""Single entry point for all IBSng API calls. Handlers and other
services must never call IBSng directly - always go through
IBSngClient.

Transport: XML-RPC over HTTP to IBSNG_BASE_URL (default port 1235 for
IBSng Free 1.24). Credentials are sent on EVERY call (auth_type=ADMIN,
auth_name, auth_pass, auth_remoteaddr merged into each method's
params) - this edition does not support reusable sessions.

Ported from AloBot's IBSngClient (/Users/peyman/telegram-bot), which
confirmed the following against a real IBSng Free 1.24 server - all of
it still applies here, same server:
- group.listGroups returns a plain list of group name strings.
- user.doesUserExists is not a valid handler method; existence checks
  call user.getUserInfo and treat a Fault as "does not exist".
- Create-user is user.addNewUsers(count, isp_name, owner_name,
  group_name, credit, credit_comment) -> [user_id], then
  user.updateUserAttrs to set normal_username/normal_password with a
  FLAT six-key attrs shape (not the nested normal_user_spec shape the
  commercial docs describe - that shape is silently ignored here).
  owner_name is REQUIRED, defaults to IBSNG_USERNAME.
- user.getUserInfo's stored password and nearest_exp_date live under
  "attrs", not "basic_info".
- Changing a user's group is user.updateUserAttrs with attrs=
  {"group_name": <new name>} - group_id is silently ignored.
- Locking a user is user.updateUserAttrs with attrs={"lock": bool}.
- user_balance.getUserBalanceInfoByUserID is CONFIRMED DEAD on this
  server ("Handler --user_balance-- not found", confirmed live twice
  in AloBot's history) - do not use it for anything, including the
  quota feature (deferred to the My Services plan, which must probe
  for a working alternative first - see docs/superpowers/specs/
  2026-09-14-homeland-bot-design.md §5, §14).

Deviation from AloBot: create_user takes an explicit `credit` param
instead of a hardcoded default - Homeland's credit must always equal
the specific plan's data cap (spec §5), so there is no sensible
project-wide default to hardcode.
"""

from __future__ import annotations

import asyncio
import secrets
import xmlrpc.client
from typing import Any
from urllib.parse import urlparse

from app.config import get_settings
from app.services.ibsng.exceptions import IBSngError, IBSngUserExistsError, IBSngUserNotFoundError

_TIMEOUT = 15.0


class _TimeoutTransport(xmlrpc.client.Transport):
    def __init__(self, timeout: float) -> None:
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host: Any) -> Any:
        connection = super().make_connection(host)
        connection.timeout = self._timeout
        return connection


class _TimeoutSafeTransport(xmlrpc.client.SafeTransport):
    def __init__(self, timeout: float) -> None:
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host: Any) -> Any:
        connection = super().make_connection(host)
        connection.timeout = self._timeout
        return connection


class IBSngClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._auth_name = settings.ibsng_username
        self._auth_pass = settings.ibsng_password
        self._auth_remoteaddr = settings.ibsng_auth_remoteaddr
        self._isp_name = settings.ibsng_isp_name
        self._owner_name = settings.ibsng_owner_name or settings.ibsng_username

        transport_cls = (
            _TimeoutSafeTransport if urlparse(settings.ibsng_base_url).scheme == "https" else _TimeoutTransport
        )
        self._proxy = xmlrpc.client.ServerProxy(
            settings.ibsng_base_url,
            transport=transport_cls(_TIMEOUT),
            allow_none=True,
        )

    async def close(self) -> None:
        return None

    async def __aenter__(self) -> "IBSngClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def list_groups(self) -> list[str]:
        raw = await self._call("group.listGroups")
        return [str(name) for name in (raw or [])]

    async def get_user_info(self, *, username: str | None = None, user_id: str | None = None) -> Any:
        params: dict[str, Any] = {}
        if username is not None:
            params["normal_username"] = username
        if user_id is not None:
            params["user_id"] = user_id
        return await self._call("user.getUserInfo", **params)

    async def verify_user_credentials(self, *, username: str, password: str) -> bool:
        info = await self._get_user_info_or_none(username=username)
        if info is None:
            return False
        _, inner = _split_user_info(info)
        if inner is None:
            return False

        stored: Any = None
        attrs = inner.get("attrs")
        if isinstance(attrs, dict):
            stored = attrs.get("normal_password")
        if stored is None:
            return False
        return secrets.compare_digest(str(stored), password)

    async def get_user_expiry(self, *, username: str) -> str | None:
        info = await self._get_user_info_or_none(username=username)
        if info is None:
            return None
        _, inner = _split_user_info(info)
        if inner is None:
            return None
        attrs = inner.get("attrs")
        if isinstance(attrs, dict):
            exp = attrs.get("nearest_exp_date")
            if exp is not None:
                return str(exp)
        return None

    async def get_user_group(self, *, username: str) -> str | None:
        info = await self._get_user_info_or_none(username=username)
        if info is None:
            return None
        _, inner = _split_user_info(info)
        if inner is None:
            return None
        basic_info = inner.get("basic_info")
        if isinstance(basic_info, dict):
            group_name = basic_info.get("group_name")
            if group_name is not None:
                return str(group_name)
        return None

    async def get_user_password(self, *, username: str) -> str | None:
        info = await self._get_user_info_or_none(username=username)
        if info is None:
            return None
        _, inner = _split_user_info(info)
        if inner is None:
            return None
        attrs = inner.get("attrs")
        if isinstance(attrs, dict):
            stored = attrs.get("normal_password")
            if stored is not None:
                return str(stored)
        return None

    async def change_user_group(self, *, username: str, group_name: str) -> None:
        user_id = await self._require_user_id(username)
        await self._call(
            "user.updateUserAttrs", user_id=user_id, attrs={"group_name": group_name}, to_del_attrs=[]
        )

    async def renew_user(self, *, username: str) -> None:
        """Mirrors IBSng's admin-panel 'reset first login' action: clears
        the first_login attribute so validity restarts from the account's
        next connection. Idempotent - deleting an already-unset attribute
        is a no-op, safe to retry."""
        user_id = await self._require_user_id(username)
        await self._call("user.updateUserAttrs", user_id=user_id, attrs={}, to_del_attrs=["first_login"])

    async def change_user_password(self, *, username: str, new_password: str) -> None:
        user_id = await self._require_user_id(username)
        await self._call(
            "user.updateUserAttrs",
            user_id=user_id,
            attrs={
                "normal_username": username,
                "normal_generate_password": False,
                "normal_generate_password_len": 8,
                "normal_password": new_password,
                "normal_save": True,
                "normal_save_usernames": True,
            },
            to_del_attrs=[],
        )

    async def lock_user(self, *, username: str, locked: bool = True) -> None:
        user_id = await self._require_user_id(username)
        await self._call("user.updateUserAttrs", user_id=user_id, attrs={"lock": locked}, to_del_attrs=[])

    async def delete_user(self, *, username: str, comment: str = "Revoked via Telegram bot") -> None:
        user_id = await self._require_user_id(username)
        await self._call(
            "user.delUser",
            user_id=user_id,
            delete_comment=comment,
            del_connection_logs=True,
            del_audit_logs=True,
        )

    async def create_user(self, *, username: str, password: str, group_name: str, credit: int) -> str:
        """Idempotent: raises IBSngUserExistsError instead of creating a
        duplicate. credit must be the purchased plan's data_cap_mb (see
        module docstring) - always pass it explicitly, there is no
        default."""
        if await self._get_user_info_or_none(username=username) is not None:
            raise IBSngUserExistsError(f"IBSng user {username!r} already exists")

        user_ids = await self._call(
            "user.addNewUsers",
            count=1,
            isp_name=self._isp_name,
            owner_name=self._owner_name,
            group_name=group_name,
            credit=credit,
            credit_comment="Created via Homeland bot",
        )
        if not user_ids:
            raise IBSngError("IBSng addNewUsers returned no user_id")
        user_id = str(user_ids[0])

        await self._call(
            "user.updateUserAttrs",
            user_id=user_id,
            attrs={
                "normal_username": username,
                "normal_generate_password": False,
                "normal_generate_password_len": 8,
                "normal_password": password,
                "normal_save": True,
                "normal_save_usernames": True,
            },
            to_del_attrs=[],
        )
        return user_id

    async def _require_user_id(self, username: str) -> str:
        info = await self._get_user_info_or_none(username=username)
        if info is None:
            raise IBSngUserNotFoundError(f"IBSng user {username!r} not found")
        user_id, _ = _split_user_info(info)
        if user_id is None:
            raise IBSngError(f"Could not determine user_id for {username!r} from getUserInfo: {info!r}")
        return user_id

    async def _get_user_info_or_none(self, *, username: str) -> Any | None:
        payload = {
            "auth_type": "ADMIN",
            "auth_name": self._auth_name,
            "auth_pass": self._auth_pass,
            "auth_remoteaddr": self._auth_remoteaddr,
            "normal_username": username,
        }
        try:
            return await asyncio.to_thread(self._proxy.user.getUserInfo, payload)
        except xmlrpc.client.Fault:
            return None
        except (xmlrpc.client.ProtocolError, OSError) as exc:
            raise IBSngError(f"IBSng call 'user.getUserInfo' could not reach server: {exc}") from exc

    async def _call(self, method: str, **params: Any) -> Any:
        payload = {
            "auth_type": "ADMIN",
            "auth_name": self._auth_name,
            "auth_pass": self._auth_pass,
            "auth_remoteaddr": self._auth_remoteaddr,
            **params,
        }
        try:
            return await asyncio.to_thread(getattr(self._proxy, method), payload)
        except xmlrpc.client.Fault as exc:
            raise IBSngError(f"IBSng call {method!r} failed: {exc.faultString}") from exc
        except (xmlrpc.client.ProtocolError, OSError) as exc:
            raise IBSngError(f"IBSng call {method!r} could not reach server: {exc}") from exc


def _split_user_info(info: Any) -> tuple[str | None, dict[str, Any] | None]:
    if not isinstance(info, dict):
        return None, None
    if "basic_info" in info:
        user_id = info.get("user_id")
        resolved = str(user_id) if user_id is not None and not isinstance(user_id, dict) else None
        return resolved, info
    if len(info) == 1:
        only_key, only_value = next(iter(info.items()))
        if isinstance(only_value, dict):
            return str(only_key), only_value
    return None, None
