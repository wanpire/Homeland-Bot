"""Log hygiene installed before anything else logs.

Plisio's API takes its secret key as a QUERY PARAMETER, and httpx logs
every request line at INFO - which on 2026-09-22 was found writing the
live key into the container logs in plain text on every invoice
creation. Redacting only our own exception strings was not enough: the
leak came from a third-party library's logger, so the filter has to sit
on the handler every logger feeds.
"""

from __future__ import annotations

import logging

_REDACTED = "***"


class SecretRedactingFilter(logging.Filter):
    """Replaces configured secrets anywhere in a record - message, args
    or formatted output - before it reaches a handler."""

    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        # Only non-trivial values: a one-character "secret" would redact
        # half the log, and a blank one would match everywhere.
        self._secrets = [s for s in secrets if s and len(s) >= 8]

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._secrets:
            return True
        if isinstance(record.msg, str) and any(s in record.msg for s in self._secrets):
            record.msg = self._scrub(record.msg)
            record.args = None if record.args is None else self._scrub_args(record.args)
            return True
        if record.args:
            record.args = self._scrub_args(record.args)
        return True

    def _scrub(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, _REDACTED)
        return text

    def _scrub_args(self, args: object) -> object:
        if isinstance(args, dict):
            return {k: self._scrub(v) if isinstance(v, str) else v for k, v in args.items()}
        if isinstance(args, tuple):
            return tuple(self._scrub(a) if isinstance(a, str) else a for a in args)
        return args


def install_secret_redaction(secrets: list[str]) -> None:
    """Attach the filter to every root handler, so it covers third-party
    loggers (httpx, aiohttp) as well as ours."""
    log_filter = SecretRedactingFilter(secrets)
    root = logging.getLogger()
    for handler in root.handlers:
        handler.addFilter(log_filter)
