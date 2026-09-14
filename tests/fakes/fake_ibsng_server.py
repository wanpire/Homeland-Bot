"""In-process fake IBSng XML-RPC server for tests. Replicates the real
server's confirmed quirks (documented in app/services/ibsng/client.py's
module docstring) closely enough that IBSngClient's code paths exercise
realistically, without ever touching the real IBSng box.

Runs as a background thread inside the pytest process - started once
per test session by the ibsng_server fixture in conftest.py, reset
between tests via .reset().
"""

from __future__ import annotations

import threading
import time
import xmlrpc.client
from typing import Any, NoReturn
from xmlrpc.server import SimpleXMLRPCServer, SimpleXMLRPCRequestHandler


class _QuietRequestHandler(SimpleXMLRPCRequestHandler):
    rpc_paths = ("/", "/RPC2")

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - matches base signature
        """Silences BaseHTTPRequestHandler's per-request stderr logging."""


class FakeIBSngServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.host = host
        self.port = port
        self._server: SimpleXMLRPCServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._users: dict[int, dict] = {}
        self._next_id = 1
        self._groups = ["HL-2W", "HL-1M", "HL-2M", "HL-3M"]

    def reset(self) -> None:
        with self._lock:
            self._users = {}
            self._next_id = 1

    def set_user_attr(self, username: str, key: str, value: Any) -> None:
        """Test-only backdoor for seeding attrs no real API call can set
        directly (e.g. nearest_exp_date)."""
        with self._lock:
            found = self._find_by_username(username)
            if found is None:
                raise KeyError(f"no fake IBSng user named {username!r}")
            _, user = found
            user["attrs"][key] = value

    def start(self) -> None:
        self._server = SimpleXMLRPCServer(
            (self.host, self.port), requestHandler=_QuietRequestHandler, allow_none=True, logRequests=False
        )
        for prefix, methods in (
            ("group", {"listGroups": self._group_listGroups}),
            (
                "user",
                {
                    "getUserInfo": self._user_getUserInfo,
                    "addNewUsers": self._user_addNewUsers,
                    "updateUserAttrs": self._user_updateUserAttrs,
                    "delUser": self._user_delUser,
                },
            ),
            ("user_balance", {"getUserBalanceInfoByUserID": self._user_balance_not_found}),
        ):
            for name, fn in methods.items():
                self._server.register_function(fn, f"{prefix}.{name}")
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        time.sleep(0.05)

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()

    def _find_by_username(self, username: str) -> tuple[int, dict] | None:
        for uid, u in self._users.items():
            if u["attrs"].get("normal_username") == username:
                return uid, u
        return None

    def _group_listGroups(self, payload: dict) -> list[str]:
        return list(self._groups)

    def _user_getUserInfo(self, payload: dict) -> dict[str, Any]:
        with self._lock:
            if "user_id" in payload:
                uid = int(payload["user_id"])
                user = self._users.get(uid)
            else:
                found = self._find_by_username(payload.get("normal_username", ""))
                uid, user = found if found else (None, None)
            if user is None:
                raise xmlrpc.client.Fault(1, "NORMAL_USERNAME_DOESNT_EXISTS|User does not exist")
            return {str(uid): {"basic_info": user["basic_info"], "attrs": user["attrs"], "user_repr": uid}}

    def _user_addNewUsers(self, payload: dict) -> list[int]:
        with self._lock:
            uid = self._next_id
            self._next_id += 1
            self._users[uid] = {
                "basic_info": {
                    "user_id": uid,
                    "group_name": payload["group_name"],
                    "owner_name": payload.get("owner_name"),
                    "credit": payload.get("credit", 0),
                },
                "attrs": {"user_id": uid},
            }
            return [uid]

    def _user_updateUserAttrs(self, payload: dict) -> bool:
        with self._lock:
            uid = int(payload["user_id"])
            user = self._users.get(uid)
            if user is None:
                raise xmlrpc.client.Fault(1, "NORMAL_USERNAME_DOESNT_EXISTS|User does not exist")
            attrs = payload.get("attrs", {})
            if "normal_username" in attrs:
                required = (
                    "normal_username", "normal_generate_password", "normal_generate_password_len",
                    "normal_password", "normal_save", "normal_save_usernames",
                )
                missing = [k for k in required if k not in attrs]
                if missing:
                    raise xmlrpc.client.Fault(1, f"KeyError: {missing[0]}")
                user["attrs"]["normal_username"] = attrs["normal_username"]
                user["attrs"]["normal_password"] = attrs["normal_password"]
            if "group_name" in attrs:
                user["basic_info"]["group_name"] = attrs["group_name"]
            if "lock" in attrs:
                user["attrs"]["lock"] = attrs["lock"]
            for key in payload.get("to_del_attrs", []):
                user["attrs"].pop(key, None)
            return True

    def _user_delUser(self, payload: dict) -> bool:
        with self._lock:
            uid = int(payload["user_id"])
            if uid not in self._users:
                raise xmlrpc.client.Fault(1, "NORMAL_USERNAME_DOESNT_EXISTS|User does not exist")
            del self._users[uid]
            return True

    def _user_balance_not_found(self, payload: dict) -> NoReturn:
        raise xmlrpc.client.Fault(1, "Handler --user_balance-- not found")
