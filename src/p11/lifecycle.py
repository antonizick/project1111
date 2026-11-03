"""Background Studio process management for ``p11 start/stop/status/open`` (spec R16).

``p11 serve`` writes ``$XDG_RUNTIME_DIR/p11/studio.json`` (pid, port, mode, start time; ``0600``)
next to the session token. The other commands find the Studio through it, check that the pid
really is a ``p11 serve`` (so a recycled pid is never signalled) and talk to it over loopback
HTTP with the token from the same directory.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

from p11 import paths
from p11.api.security import read_token, token_path
from p11.engine.process import pid_alive

STATE_FILE = "studio.json"
OUT_FILE = "studio.out"
START_TIMEOUT = 30.0
STOP_TIMEOUT = 30.0
#: Chromium-family browsers that take ``--app=<url>`` (an app-mode window).
APP_BROWSERS = (
    "chromium",
    "google-chrome-stable",
    "google-chrome",
    "brave",
    "brave-browser",
    "microsoft-edge-stable",
    "vivaldi-stable",
)


class StudioError(RuntimeError):
    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


@dataclass(frozen=True)
class StudioState:
    pid: int
    port: int
    fake: bool
    started: str
    log: str

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def state_path() -> Path:
    return paths.runtime_dir() / STATE_FILE


def write_state(state: StudioState) -> Path:
    path = state_path()
    paths.ensure_private_dir(path.parent)
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(asdict(state), fh)
    tmp.replace(path)
    return path


def read_state() -> StudioState | None:
    try:
        data = json.loads(state_path().read_text())
        return StudioState(**data)
    except (OSError, ValueError, TypeError):
        return None


def clear_state(pid: int) -> None:
    """Remove the state and token files if they still belong to ``pid``."""
    state = read_state()
    if state is None or state.pid == pid:
        state_path().unlink(missing_ok=True)
        token_path().unlink(missing_ok=True)


def is_studio_pid(pid: int) -> bool:
    """``pid`` is alive and its command line is a ``p11 serve``."""
    if not pid_alive(pid):
        return False
    try:
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except OSError:
        return False
    words = [Path(a.decode(errors="replace")).name for a in argv if a]
    return "serve" in words and "p11" in words


def healthy(port: int, timeout: float = 1.0) -> bool:
    try:
        r = httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=timeout)
    except httpx.HTTPError:
        return False
    return r.status_code == 200 and r.json().get("status") == "ok"


def running() -> StudioState | None:
    """The live Studio, or ``None`` (stale state files are cleaned up)."""
    state = read_state()
    if state is None:
        return None
    if not is_studio_pid(state.pid):
        clear_state(state.pid)
        return None
    return state


def api(state: StudioState, method: str, path: str, **kwargs: Any) -> httpx.Response:
    token = read_token()
    if token is None:
        raise StudioError("The Studio's session token is missing.", "Run `p11 stop && p11 start`.")
    headers = {"authorization": f"Bearer {token}", **kwargs.pop("headers", {})}
    return httpx.request(
        method, f"{state.url}{path}", headers=headers, timeout=kwargs.pop("timeout", 10.0), **kwargs
    )


def start_background(
    *, fake: bool = False, port: int | None = None, debug: bool = False
) -> StudioState:
    """Start ``p11 serve`` detached and wait until it answers ``/healthz``."""
    current = running()
    if current is not None:
        return current
    argv = [sys.executable, "-m", "p11", "serve"]
    if fake:
        argv.append("--fake")
    if port is not None:
        argv += ["--port", str(port)]
    if debug:
        argv.append("--debug")
    out = paths.ensure_private_dir(paths.logs_dir()) / OUT_FILE
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    deadline = time.monotonic() + START_TIMEOUT
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            tail = out.read_text(errors="replace").strip().splitlines()[-5:]
            raise StudioError(
                "P11 Studio exited while starting" + (f": {tail[-1]}" if tail else "."),
                f"See {out} and `p11 doctor`.",
            )
        state = read_state()
        if state is not None and state.pid == proc.pid and healthy(state.port, timeout=0.5):
            return state
        time.sleep(0.2)
    proc.terminate()
    raise StudioError("P11 Studio did not start in time.", f"See {out}.")


def stop(timeout: float = STOP_TIMEOUT) -> StudioState | None:
    """SIGTERM the Studio (it stops the engine on the way out); SIGKILL after ``timeout``."""
    state = running()
    if state is None:
        return None
    os.kill(state.pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_alive(state.pid):
            break
        time.sleep(0.1)
    else:
        os.kill(state.pid, signal.SIGKILL)
    clear_state(state.pid)
    return state


def browser_command(url: str) -> list[str]:
    """How ``p11 open`` shows the UI: like an Omarchy web app, else app mode, else ``xdg-open``.

    ``$P11_BROWSER`` (a command; the URL is appended) overrides the detection.
    """
    override = os.environ.get("P11_BROWSER")
    if override:
        return [*override.split(), url]
    launcher = shutil.which("omarchy-launch-webapp")
    if launcher:
        return [launcher, url]
    for name in APP_BROWSERS:
        found = shutil.which(name)
        if found:
            return [found, f"--app={url}"]
    opener = shutil.which("xdg-open")
    if opener:
        return [opener, url]
    raise StudioError("No browser found to open P11 Studio.", f"Open {url.split('#')[0]} yourself.")


def launch_url(state: StudioState) -> str:
    """A URL with a fresh one-time launch code in the fragment (never sent to the server)."""
    r = api(state, "POST", "/api/session/launch")
    if r.status_code != 200:
        raise StudioError(f"The Studio refused a launch code (HTTP {r.status_code}).")
    return f"{state.url}/#launch={r.json()['code']}"


def open_browser(url: str) -> list[str]:
    cmd = browser_command(url)
    subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return cmd
