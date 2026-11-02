"""Start/stop the pinned headless ComfyUI and talk to its HTTP + websocket API (bench only).

Phase 05 replaces this with ``p11.engine``; this module exists so the bake-off is reproducible.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import tomllib
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from websockets.sync.client import connect

REPO = Path(__file__).resolve().parents[2]
LOCK = tomllib.loads((REPO / "engine/engine.lock.toml").read_text())
DATA = Path(os.environ.get("P11_DATA_DIR") or Path.home() / ".local/share/p11")
CACHE = Path(os.environ.get("P11_CACHE_DIR") or Path.home() / ".cache/p11")
ENGINE = DATA / "engine"
BENCH = CACHE / "bench"

# VRAM modes compared in the bake-off (flags verified in comfy/cli_args.py at the pin).
VRAM_MODES: dict[str, list[str]] = {
    "dynamic": [],  # default at v0.43.0: dynamic VRAM
    "classic": ["--disable-dynamic-vram"],
    "lowvram": ["--disable-dynamic-vram", "--lowvram"],
}


class EngineError(RuntimeError):
    pass


@dataclass
class Engine:
    vram_mode: str = "dynamic"
    port: int = int(LOCK["launch"]["port"])
    extra: list[str] = field(default_factory=list)
    proc: subprocess.Popen[bytes] | None = None
    log_path: Path | None = None

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def command(self) -> list[str]:
        d = BENCH / "engine"
        for sub in ("out", "in", "tmp", "user"):
            (d / sub).mkdir(parents=True, exist_ok=True, mode=0o700)
        return [
            str(ENGINE / "venv/bin/python"), "main.py",
            "--listen", LOCK["launch"]["listen"], "--port", str(self.port),
            *LOCK["launch"]["flags"],
            "--extra-model-paths-config", str(ENGINE / "extra_model_paths.yaml"),
            "--output-directory", str(d / "out"), "--input-directory", str(d / "in"),
            "--temp-directory", str(d / "tmp"), "--user-directory", str(d / "user"),
            "--database-url", f"sqlite:///{d / 'user' / 'comfyui.db'}",
            *VRAM_MODES[self.vram_mode], *self.extra,
        ]

    def start(self, timeout: float = 180) -> None:
        BENCH.mkdir(parents=True, exist_ok=True)
        self.log_path = BENCH / f"engine-{self.vram_mode}-{int(time.time())}.log"
        log = self.log_path.open("wb")
        self.proc = subprocess.Popen(
            self.command(), cwd=ENGINE / "ComfyUI", stdout=log, stderr=subprocess.STDOUT,
            env={**os.environ, "COMFYUI_DISABLE_PRODUCT_TIPS": "1", "HF_HUB_OFFLINE": "1",
                 "DO_NOT_TRACK": "1"},
            start_new_session=True,
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise EngineError(f"engine exited with {self.proc.returncode}; see {self.log_path}")
            try:
                if httpx.get(f"{self.base}/system_stats", timeout=2).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        raise EngineError(f"engine not ready after {timeout}s; see {self.log_path}")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGTERM)
            try:
                self.proc.wait(30)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL)
                self.proc.wait(10)
        self.proc = None

    def __enter__(self) -> Engine:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def free(self) -> None:
        httpx.post(f"{self.base}/free", json={"unload_models": True, "free_memory": True}, timeout=30)
        time.sleep(1.0)

    def object_info(self, node: str) -> dict[str, Any]:
        r: dict[str, Any] = httpx.get(f"{self.base}/object_info/{node}", timeout=30).json()
        return r

    def run(self, graph: dict[str, Any], timeout: float = 900) -> RunResult:
        """Queue ``graph``, follow the websocket until it finishes; return timings and outputs."""
        client_id = uuid.uuid4().hex
        res = RunResult()
        with connect(f"ws://127.0.0.1:{self.port}/ws?clientId={client_id}", max_size=None,
                     open_timeout=30) as ws:
            t0 = time.time()
            r = httpx.post(f"{self.base}/prompt", json={"prompt": graph, "client_id": client_id},
                           timeout=30)
            body = r.json()
            if r.status_code != 200:
                raise EngineError(f"prompt rejected: {json.dumps(body)[:2000]}")
            pid = body["prompt_id"]
            deadline = t0 + timeout
            while True:
                if time.time() > deadline:
                    raise EngineError("timeout")
                msg = ws.recv(timeout=max(1.0, deadline - time.time()))
                if isinstance(msg, bytes):
                    continue
                m = json.loads(msg)
                typ, data = m.get("type"), m.get("data", {})
                if data.get("prompt_id") not in (None, pid):
                    continue
                now = time.time()
                if typ == "progress":
                    node = data.get("node")
                    res.progress.setdefault(node, []).append((now, data["value"], data["max"]))
                elif typ == "executing" and data.get("node") is not None:
                    res.node_start.setdefault(data["node"], now)
                elif typ == "execution_error":
                    res.error = f"{data.get('exception_type')}: {data.get('exception_message')}"
                    res.seconds = now - t0
                    break
                elif typ == "execution_success" or (typ == "executing" and data.get("node") is None):
                    res.seconds = now - t0
                    break
        hist = httpx.get(f"{self.base}/history/{pid}", timeout=30).json().get(pid, {})
        for out in hist.get("outputs", {}).values():
            for img in out.get("images", []):
                res.images.append(BENCH / "engine/out" / img.get("subfolder", "") / img["filename"])
        return res

    def rss_mib(self) -> int | None:
        if not self.proc:
            return None
        try:
            for line in Path(f"/proc/{self.proc.pid}/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) // 1024
        except OSError:
            return None
        return None


@dataclass
class RunResult:
    seconds: float | None = None
    error: str | None = None
    images: list[Path] = field(default_factory=list)
    progress: dict[str, list[tuple[float, int, int]]] = field(default_factory=dict)
    node_start: dict[str, float] = field(default_factory=dict)

    def it_per_s(self, node: str) -> float | None:
        p = self.progress.get(node)
        if not p or len(p) < 2:
            return None
        (t0, v0, _), (t1, v1, _) = p[0], p[-1]
        return (v1 - v0) / (t1 - t0) if t1 > t0 else None
