"""Sample GPU state with nvidia-smi in a background thread (VRAM, temperature, clocks, power)."""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass, field

FIELDS = "memory.used,temperature.gpu,clocks.sm,power.draw,clocks_throttle_reasons.active,utilization.gpu"


def query() -> dict[str, float]:
    out = subprocess.run(
        ["nvidia-smi", f"--query-gpu={FIELDS}", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, check=True,
    ).stdout.strip().split(", ")
    return parse(out)


def parse(cols: list[str]) -> dict[str, float]:
    def num(s: str) -> float:
        s = s.strip()
        if s.startswith("0x"):
            return float(int(s, 16))
        try:
            return float(s)
        except ValueError:
            return float("nan")

    keys = ["vram_mib", "temp_c", "sm_mhz", "power_w", "throttle", "util"]
    return dict(zip(keys, (num(c) for c in cols), strict=False))


@dataclass
class Monitor:
    interval_ms: int = 200
    samples: list[tuple[float, dict[str, float]]] = field(default_factory=list)
    _proc: subprocess.Popen[str] | None = None
    _thread: threading.Thread | None = None

    def __enter__(self) -> Monitor:
        self._proc = subprocess.Popen(
            ["nvidia-smi", f"--query-gpu={FIELDS}", "--format=csv,noheader,nounits", f"-lms={self.interval_ms}"],
            stdout=subprocess.PIPE, text=True,
        )
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()
        return self

    def _read(self) -> None:
        assert self._proc and self._proc.stdout
        for line in self._proc.stdout:
            self.samples.append((time.time(), parse(line.strip().split(", "))))

    def __exit__(self, *exc: object) -> None:
        if self._proc:
            self._proc.terminate()
            self._proc.wait(5)
        if self._thread:
            self._thread.join(2)

    def peak(self, key: str) -> float | None:
        vals = [s[key] for _, s in self.samples if s.get(key) == s.get(key)]
        return max(vals) if vals else None
