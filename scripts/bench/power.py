"""Power profile handling for GPU runs (spec H8): performance during runs, restore afterwards."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def on_ac() -> bool:
    for p in Path("/sys/class/power_supply").glob("*"):
        t = (p / "type").read_text().strip() if (p / "type").exists() else ""
        if t == "Mains" and (p / "online").exists():
            return (p / "online").read_text().strip() == "1"
    return False


def get_profile() -> str:
    return subprocess.run(["powerprofilesctl", "get"], capture_output=True, text=True, check=True).stdout.strip()


@contextmanager
def performance() -> Iterator[str]:
    if os.environ.get("P11_BENCH_KEEP_POWER") == "1":  # gpu smoke test: leave the profile alone
        yield get_profile()
        return
    if not on_ac():
        raise SystemExit("On battery: GPU benchmarks are blocked (spec H8).")
    previous = get_profile()
    subprocess.run(["powerprofilesctl", "set", "performance"], check=True)
    try:
        yield previous
    finally:
        subprocess.run(["powerprofilesctl", "set", previous], check=False)
