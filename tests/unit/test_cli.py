"""CLI: version/paths, serve wiring, and the start/stop/status/open lifecycle (fake engine)."""

from __future__ import annotations

import json
import os
import socket
import stat

import httpx
import pytest
from typer.testing import CliRunner

from p11 import __version__, lifecycle
from p11.cli import app

runner = CliRunner()


def test_version():
    r = runner.invoke(app, ["version"])
    assert r.exit_code == 0
    assert r.stdout.strip() == __version__


def test_paths(tmp_path):
    r = runner.invoke(app, ["paths"])
    assert r.exit_code == 0
    assert str(tmp_path / "config") in r.stdout


def test_update_and_uninstall_are_commands():
    r = runner.invoke(app, ["update", "--help"])
    assert r.exit_code == 0 and "--dry-run" in r.stdout and "--to" in r.stdout
    assert runner.invoke(app, ["uninstall", "--help"]).exit_code == 0


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_serve_wires_the_app(monkeypatch, tmp_path):
    from p11.engine.comfy import ComfyEngine
    from p11.engine.fake import FakeEngine

    seen: dict[str, object] = {}

    def fake_run(application, **kw):  # type: ignore[no-untyped-def]
        seen.update(app=application, **kw)
        state = lifecycle.read_state()
        seen["state"] = state
        seen["token_mode"] = stat.S_IMODE((tmp_path / "run" / "studio.token").stat().st_mode)

    monkeypatch.setattr("p11.cli.uvicorn.run", fake_run)
    port = _free_port()
    result = runner.invoke(app, ["serve", "--fake", "--port", str(port)])
    assert result.exit_code == 0, result.output
    assert isinstance(seen["app"].state.engine, FakeEngine)
    assert seen["host"] == "127.0.0.1" and seen["port"] == port
    assert seen["access_log"] is False and seen["log_config"] is None
    assert seen["state"].pid == os.getpid() and seen["state"].fake is True
    assert seen["token_mode"] == 0o600
    assert seen["app"].state.studio.paths.outputs == tmp_path / "cache" / "fake" / "pictures"
    assert lifecycle.read_state() is None  # cleaned up on exit
    assert not (tmp_path / "run" / "studio.token").exists()
    runner.invoke(app, ["serve", "--port", str(port)])
    assert isinstance(seen["app"].state.engine, ComfyEngine)


def test_serve_refuses_a_busy_port(monkeypatch):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        monkeypatch.setattr("p11.cli.uvicorn.run", lambda *a, **k: None)
        r = runner.invoke(app, ["serve", "--fake", "--port", str(port)])
    assert r.exit_code == 1 and "already in use" in r.output


def test_start_status_open_stop_with_the_fake_engine(tmp_path, monkeypatch):
    port = _free_port()
    monkeypatch.setenv("P11_STUDIO_PORT", str(port))
    r = runner.invoke(app, ["status"])
    assert r.exit_code == 3 and "not running" in r.output
    r = runner.invoke(app, ["start", "--fake"])
    assert r.exit_code == 0, r.output
    try:
        state = lifecycle.running()
        assert state is not None and state.port == port and state.fake
        assert "already running" in runner.invoke(app, ["start", "--fake"]).output
        r = runner.invoke(app, ["status"])
        assert r.exit_code == 0 and "fake engine" in r.output and "Queue" in r.output
        data = json.loads(runner.invoke(app, ["status", "--json"]).output)
        assert data["running"] and data["engine"]["vram_mode"] == "dynamic"
        assert (
            runner.invoke(app, ["status", "--token-file"]).output.strip().endswith("studio.token")
        )
        url = runner.invoke(app, ["open", "--print-url"]).output.strip()
        assert url.startswith(f"http://127.0.0.1:{port}/#launch=")
        code = url.split("#launch=")[1]
        redeemed = httpx.post(f"http://127.0.0.1:{port}/api/session", json={"code": code})
        assert redeemed.status_code == 200
        # the browser launcher gets the one-time URL
        seen: list[list[str]] = []
        monkeypatch.setattr(lifecycle, "open_browser", lambda u: seen.append([u]) or [u])
        assert runner.invoke(app, ["open"]).exit_code == 0 and "#launch=" in seen[0][0]
        # nothing listens anywhere but loopback
        assert httpx.get(f"http://127.0.0.1:{port}/healthz").status_code == 200
        log = (tmp_path / "cache" / "logs" / "studio.log").read_text()
        token = (tmp_path / "run" / "studio.token").read_text()
        assert token not in log and code not in log
    finally:
        r = runner.invoke(app, ["stop"])
    assert r.exit_code == 0 and "stopped" in r.output
    assert lifecycle.running() is None
    assert "not running" in runner.invoke(app, ["stop"]).output


def test_open_starts_the_studio_when_needed(monkeypatch):
    calls = []
    state = lifecycle.StudioState(pid=1, port=1, fake=False, started="", log="")
    monkeypatch.setattr(lifecycle, "running", lambda: None)
    monkeypatch.setattr(lifecycle, "start_background", lambda: calls.append("start") or state)
    monkeypatch.setattr(lifecycle, "launch_url", lambda s: "http://127.0.0.1:1/#launch=x")
    r = runner.invoke(app, ["open", "--print-url"])
    assert calls == ["start"] and "launch=x" in r.output


def test_start_failure_is_explained(monkeypatch):
    def boom(**_):  # type: ignore[no-untyped-def]
        raise lifecycle.StudioError("P11 Studio exited while starting.", "See the log.")

    monkeypatch.setattr(lifecycle, "start_background", boom)
    r = runner.invoke(app, ["start"])
    assert r.exit_code == 1 and "exited while starting" in r.output and "Hint" in r.output


def test_stale_state_is_cleaned_up(tmp_path):
    lifecycle.write_state(lifecycle.StudioState(pid=2**22 + 7, port=1, fake=False, started="",
                                                log=""))  # fmt: skip
    assert lifecycle.running() is None
    assert lifecycle.read_state() is None


def test_a_recycled_pid_is_not_ours():
    assert not lifecycle.is_studio_pid(os.getpid())  # pytest is not `p11 serve`
    assert not lifecycle.is_studio_pid(2**22 + 9)


@pytest.mark.parametrize(
    ("have", "expect"),
    [
        ({"omarchy-launch-webapp"}, ["/bin/omarchy-launch-webapp", "URL"]),
        ({"chromium", "xdg-open"}, ["/bin/chromium", "--app=URL"]),
        ({"brave", "xdg-open"}, ["/bin/brave", "--app=URL"]),
        ({"xdg-open"}, ["/bin/xdg-open", "URL"]),
    ],
)
def test_browser_detection(monkeypatch, have, expect):
    monkeypatch.delenv("P11_BROWSER", raising=False)
    monkeypatch.setattr(lifecycle.shutil, "which", lambda n: f"/bin/{n}" if n in have else None)
    assert lifecycle.browser_command("URL") == expect


def test_browser_override_and_none(monkeypatch):
    monkeypatch.setenv("P11_BROWSER", "firefox --new-window")
    assert lifecycle.browser_command("U") == ["firefox", "--new-window", "U"]
    monkeypatch.delenv("P11_BROWSER")
    monkeypatch.setattr(lifecycle.shutil, "which", lambda n: None)
    with pytest.raises(lifecycle.StudioError, match="No browser"):
        lifecycle.browser_command("http://x/#launch=secret")
