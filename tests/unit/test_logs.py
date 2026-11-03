"""Structured log with redaction (S6, S9)."""

from __future__ import annotations

import json
import logging

from p11 import logs


def test_json_lines_private_file_and_redaction(tmp_path):
    path = logs.setup_logging(path=tmp_path / "logs" / "studio.log")
    secret = "s3cr3t-token-value-0123456789"
    logs.register_secret(secret)
    log = logging.getLogger("p11.test")
    log.info("hello %s", secret, extra={"job": "j1", "n": 2})
    try:
        raise RuntimeError(f"boom {secret}")
    except RuntimeError:
        log.exception("failed")
    logs.debug_private(log, "prompt was %s", "a private prompt")
    for h in logging.getLogger("p11").handlers:
        h.flush()
    text = path.read_text()
    assert secret not in text and "[redacted]" in text
    assert "a private prompt" not in text  # DEBUG only
    first = json.loads(text.splitlines()[0])
    assert first["msg"] == "hello [redacted]" and first["job"] == "j1" and first["n"] == 2
    assert "boom [redacted]" in json.loads(text.splitlines()[1])["exc"]
    assert path.stat().st_mode & 0o777 == 0o600
    assert logging.getLogger("uvicorn.access").disabled
    logs.forget_secret(secret)
    assert logs.redact(secret) == secret


def test_debug_logs_private_text_but_still_redacts_the_token(tmp_path):
    path = logs.setup_logging(debug=True, path=tmp_path / "studio.log")
    secret = "another-secret-token-abcdef"
    logs.register_secret(secret)
    log = logging.getLogger("p11.test")
    logs.debug_private(log, "prompt %s token %s", "a lighthouse", secret)
    for h in logging.getLogger("p11").handlers:
        h.flush()
    text = path.read_text()
    assert "a lighthouse" in text and secret not in text
    logs.setup_logging(path=tmp_path / "studio.log")  # back to INFO, handler replaced
    assert len([h for h in logging.getLogger("p11").handlers if getattr(h, "_p11", False)]) == 1


def test_short_values_are_not_registered():
    logs.register_secret("abc")
    assert logs.redact("abc") == "abc"
