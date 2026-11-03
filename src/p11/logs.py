"""Structured Studio logging (spec S6, S9): JSON lines to ``~/.cache/p11/logs/studio.log``.

Rotated at 5 MB, three files kept, ``0600``. Two rules keep private data out:

* nothing logs prompt text, bindings or file contents at INFO; code that wants them for debugging
  logs at DEBUG through ``debug_private`` (only with ``--debug``);
* every registered secret (the session token, launch codes) is replaced with ``[redacted]`` in
  every record at every level, including uvicorn's and exceptions' text.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import threading
import time
from pathlib import Path
from typing import Any

from p11 import paths

LOG_NAME = "studio.log"
ROTATE_BYTES = 5 * 1024 * 1024
KEEP = 3
REDACTED = "[redacted]"
#: Secrets shorter than this are not registered (they would redact ordinary words).
MIN_SECRET = 12

_secrets: set[str] = set()
_lock = threading.Lock()


def register_secret(value: str) -> None:
    """Redact ``value`` from every log record from now on."""
    if len(value) >= MIN_SECRET:
        with _lock:
            _secrets.add(value)


def forget_secret(value: str) -> None:
    with _lock:
        _secrets.discard(value)


def redact(text: str) -> str:
    with _lock:
        secrets = sorted(_secrets, key=len, reverse=True)
    for s in secrets:
        if s in text:
            text = text.replace(s, REDACTED)
    return text


class RedactingFilter(logging.Filter):
    """Formats the message once, redacts it and drops the args (so formatters cannot re-leak)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        record.exc_info = None
        return True


#: ``LogRecord`` attributes that are not user ``extra=`` fields.
_STANDARD = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD and not key.startswith("_"):
                out[key] = value if isinstance(value, int | float | bool | None) else str(value)
        if record.exc_text:
            out["exc"] = record.exc_text
        return redact(json.dumps(out, ensure_ascii=False))


class _PrivateRotatingHandler(logging.handlers.RotatingFileHandler):
    def _open(self):  # type: ignore[no-untyped-def]
        fd = os.open(self.baseFilename, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        os.chmod(self.baseFilename, 0o600)
        return os.fdopen(fd, "a", encoding="utf-8")


def log_path() -> Path:
    return paths.logs_dir() / LOG_NAME


def setup_logging(*, debug: bool = False, path: Path | None = None) -> Path:
    """Send the ``p11`` and ``uvicorn`` loggers to the rotated JSON log; returns its path."""
    path = path or log_path()
    paths.ensure_private_dir(path.parent)
    handler = _PrivateRotatingHandler(path, maxBytes=ROTATE_BYTES, backupCount=KEEP)
    handler.addFilter(RedactingFilter())
    handler.setFormatter(JsonFormatter())
    level = logging.DEBUG if debug else logging.INFO
    for name in ("p11", "uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        for old in list(logger.handlers):
            if getattr(old, "_p11", False):
                logger.removeHandler(old)
                old.close()
        handler._p11 = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = False
    # The access log carries query strings (gallery search text): P11 logs requests itself.
    logging.getLogger("uvicorn.access").disabled = True
    return path


def debug_private(logger: logging.Logger, msg: str, *args: object) -> None:
    """Log something that may contain prompt text or bindings: DEBUG only, never at INFO (S6)."""
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(msg, *args)
