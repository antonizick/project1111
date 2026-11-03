"""``p11 doctor``: is this machine ready to run P11, and if not, what to do about it.

Each check returns ``Check`` lines (what is fine) and ``Problem``s (what is not, with a hint).
Checks are independent and never raise: a broken part shows up as a problem, not a traceback.
"""

from __future__ import annotations

import json
import re
import shutil
import stat
import subprocess
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from p11 import paths
from p11.config import Settings, load_settings
from p11.engine.lockfile import EngineLock, find_lock_file, load_lock
from p11.engine.process import pid_alive, port_in_use, read_pid_file
from p11.problems import Problem

LOW_DISK_OUTPUTS = 5 * 1000**3
TORCH_TIMEOUT = 180.0
_VERSION = re.compile(r"""__version__\s*=\s*["']([^"']+)["']""")
TORCH_PROBE = (
    "import json, torch; ok = torch.cuda.is_available(); "
    "print(json.dumps({'torch': torch.__version__, 'cuda': ok, "
    "'capability': list(torch.cuda.get_device_capability(0)) if ok else None, "
    "'arch': torch.cuda.get_arch_list() if ok else []}))"
)


@dataclass(frozen=True)
class Check:
    name: str
    detail: str


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(p.severity == "error" for p in self.problems)

    def as_json(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "checks": [{"name": c.name, "detail": c.detail} for c in self.checks],
            "problems": [p.as_json() for p in self.problems],
        }


Runner = Callable[[list[str], float], subprocess.CompletedProcess[str]]


def _run(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)


def check_gpu(report: Report, run: Runner = _run) -> None:
    smi = shutil.which("nvidia-smi")
    if smi is None:
        report.problems.append(
            Problem(
                "error",
                "gpu.missing",
                "No NVIDIA driver found (nvidia-smi is not installed).",
                "P11 needs an NVIDIA GPU and its driver; see the user guide. P11 never "
                "installs drivers itself.",
            )
        )
        return
    try:
        r = run([smi, "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"], 15)
    except (OSError, subprocess.TimeoutExpired):
        r = None
    if r is None or r.returncode != 0 or not r.stdout.strip():
        report.problems.append(
            Problem(
                "error",
                "gpu.unavailable",
                "nvidia-smi cannot talk to the GPU.",
                "Check `nvidia-smi`; after a driver update, reboot.",
            )
        )
        return
    fields = [p.strip() for p in r.stdout.splitlines()[0].split(",")]
    name, driver, memory = [*fields, "", ""][:3]
    report.checks.append(Check("gpu", f"{name}, driver {driver}, {memory}"))


def _engine_version(comfy_dir: Path) -> str | None:
    try:
        m = _VERSION.search((comfy_dir / "comfyui_version.py").read_text())
    except OSError:
        return None
    return m.group(1) if m else None


def check_engine(report: Report, *, quick: bool = False, run: Runner = _run) -> None:
    from p11.engine.comfy import EngineConfig

    try:
        lock = load_lock()
    except (OSError, KeyError, ValueError) as exc:
        report.problems.append(
            Problem(
                "error",
                "engine.lock",
                f"The engine pin file cannot be read ({find_lock_file()}): {exc}.",
                "Reinstall P11 (./install.sh) or restore engine/engine.lock.toml.",
            )
        )
        return
    cfg = EngineConfig.default(lock=lock)
    if not cfg.python.exists() or not cfg.comfy_dir.is_dir():
        report.problems.append(
            Problem(
                "error",
                "engine.missing",
                f"The engine is not installed in {cfg.engine_dir}.",
                "Run scripts/engine_setup.sh (or ./install.sh).",
            )
        )
        return
    have = _engine_version(cfg.comfy_dir)
    if have != lock.version:
        report.problems.append(
            Problem(
                "error",
                "engine.version",
                f"The installed engine is ComfyUI {have or 'unknown'}, P11 is pinned to "
                f"{lock.tag}.",
                "Re-run scripts/engine_setup.sh to install the pinned version.",
            )
        )
    else:
        report.checks.append(Check("engine", f"ComfyUI {lock.tag} ({lock.commit[:7]}) pinned"))
    if not quick:
        _check_torch(report, cfg.python, lock, run)


def _check_torch(report: Report, python: Path, lock: EngineLock, run: Runner) -> None:
    want = str(tomllib.loads(lock.path.read_text()).get("torch", {}).get("torch", ""))
    try:
        r = run([str(python), "-c", TORCH_PROBE], TORCH_TIMEOUT)
        info = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
        info = None
    if not isinstance(info, dict):
        report.problems.append(
            Problem(
                "error",
                "engine.torch",
                "The engine's PyTorch does not load.",
                "Re-run scripts/engine_setup.sh; see the Phase 03 notes in the user guide.",
            )
        )
        return
    if want and info.get("torch") != want:
        report.problems.append(
            Problem(
                "warning",
                "engine.torch-version",
                f"The engine has torch {info.get('torch')}, the pin is {want}.",
                "Re-run scripts/engine_setup.sh.",
            )
        )
    cap = info.get("capability")
    arch = info.get("arch") or []
    if not info.get("cuda") or not cap:
        report.problems.append(
            Problem(
                "error",
                "engine.cuda",
                "The engine's PyTorch cannot use the GPU (CUDA not available).",
                "Check `nvidia-smi`; reboot after a driver update.",
            )
        )
        return
    sm = f"sm_{cap[0]}{cap[1]}"
    if sm not in arch:
        report.problems.append(
            Problem(
                "error",
                "engine.arch",
                f"This PyTorch build has no kernels for the GPU ({sm}; built for {arch}).",
                "Re-run scripts/engine_setup.sh to get the pinned CUDA build.",
            )
        )
        return
    report.checks.append(Check("torch", f"torch {info.get('torch')}, CUDA OK, {sm}"))


def check_models(report: Report) -> None:
    from p11 import models

    try:
        problems = models.check()
    except Exception as exc:  # a broken manifest or state file is a problem, not a crash
        report.problems.append(
            Problem("error", "models.unreadable", f"Model state cannot be read: {exc}.", "")
        )
        return
    report.problems += problems
    if not any(p.severity == "error" for p in problems):
        report.checks.append(Check("models", "default set installed and verified by size"))


def check_ports(report: Report, settings: Settings) -> None:
    from p11 import lifecycle

    studio = lifecycle.running()
    if studio is not None:
        report.checks.append(Check("studio", f"running at {studio.url} (pid {studio.pid})"))
    elif port_in_use(settings.host, settings.studio_port):
        report.problems.append(
            Problem(
                "error",
                "ports.studio",
                f"Port {settings.studio_port} is used by another program.",
                "Stop that program or set studio_port in ~/.config/p11/config.toml.",
            )
        )
    else:
        report.checks.append(Check("studio port", f"{settings.studio_port} free"))
    pid_file = read_pid_file(paths.cache_dir() / "engine.pid")
    engine_pid = pid_file.get("pid") if pid_file else None
    ours = isinstance(engine_pid, int) and pid_alive(engine_pid)
    if port_in_use(settings.host, settings.engine_port) and not ours:
        report.problems.append(
            Problem(
                "error",
                "ports.engine",
                f"Port {settings.engine_port} (the engine's) is used by another program.",
                "Stop it (another ComfyUI?) or set engine_port in ~/.config/p11/config.toml.",
            )
        )
    else:
        state = f"P11's engine running (pid {engine_pid})" if ours else "free"
        report.checks.append(Check("engine port", f"{settings.engine_port} {state}"))


def check_disk(
    report: Report, settings: Settings, free: Callable[[Path], int] | None = None
) -> None:
    free = free or (lambda p: shutil.disk_usage(p).free)
    root = settings.outputs_root
    probe = root if root.exists() else next((p for p in root.parents if p.exists()), Path("/"))
    left = free(probe)
    if left < LOW_DISK_OUTPUTS:
        report.problems.append(
            Problem(
                "warning",
                "disk.outputs",
                f"Only {left / 1000**3:.1f} GB free for outputs ({probe}).",
                "Free some space or set outputs_root in ~/.config/p11/config.toml.",
            )
        )
    else:
        report.checks.append(Check("disk", f"{left / 1000**3:.0f} GB free for outputs"))


def check_permissions(report: Report, settings: Settings) -> None:
    """Private directories must not be readable by other users (S6)."""
    private_dirs = [
        paths.data_dir(),
        paths.inputs_dir(),
        paths.cache_dir(),
        paths.config_dir(),
        settings.outputs_root,
    ]
    private_files = [paths.config_dir() / "secrets.toml", paths.runtime_dir() / "studio.token"]
    bad = []
    for d in private_dirs:
        if d.is_dir() and stat.S_IMODE(d.stat().st_mode) & 0o077:
            bad.append(f"chmod 700 '{d}'")
    for f in private_files:
        if f.is_file() and stat.S_IMODE(f.stat().st_mode) & 0o077:
            bad.append(f"chmod 600 '{f}'")
    if bad:
        report.problems.append(
            Problem(
                "warning",
                "permissions",
                "Some P11 data is readable by other users on this machine.",
                "Run: " + " && ".join(bad),
            )
        )
    else:
        report.checks.append(Check("permissions", "data, outputs and secrets are private"))


def run_checks(*, quick: bool = False, settings: Settings | None = None) -> Report:
    settings = settings or load_settings()
    report = Report()
    check_gpu(report)
    check_engine(report, quick=quick)
    check_models(report)
    check_ports(report, settings)
    check_disk(report, settings)
    check_permissions(report, settings)
    return report
