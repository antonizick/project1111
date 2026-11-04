"""install.sh / uninstall.sh with a fake os-release, nvidia-smi and pacman (no root, no GPU)."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def fake(bin_dir: Path, name: str, body: str) -> None:
    f = bin_dir / name
    f.write_text("#!/usr/bin/env bash\n" + body + "\n")
    f.chmod(f.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    osr = tmp_path / "os-release"
    osr.write_text('ID=omarchy\nID_LIKE=arch\nPRETTY_NAME="Omarchy"\n')
    fake(bin_dir, "nvidia-smi", 'echo "NVIDIA GeForce RTX 2070, 615.78.08, 8192 MiB"')
    fake(
        bin_dir,
        "pacman",
        'case "$1" in -Q) exit 0;; -Si) exit 1;; *) echo "pacman $*" >> "$FAKE_LOG";; esac',
    )
    fake(bin_dir, "sudo", 'echo "sudo $*" >> "$FAKE_LOG"; "$@"')
    home = tmp_path / "home"
    home.mkdir()
    return {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HOME": str(home),
        "P11_OS_RELEASE": str(osr),
        "FAKE_LOG": str(tmp_path / "log"),
        "XDG_DATA_HOME": str(home / ".local/share"),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
    }


def run(script: str, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(ROOT / script), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_dry_run_changes_nothing(env: dict[str, str]) -> None:
    r = run("install.sh", env, "--dry-run", "--models", "none")
    assert r.returncode == 0, r.stderr
    assert "Driver 615.78.08 >= 580: ok" in r.stdout
    assert "Dry run finished: nothing was changed." in r.stdout
    assert not (Path(env["HOME"]) / ".local").exists()
    assert not Path(env["FAKE_LOG"]).exists()


@pytest.fixture
def checkout(env: dict[str, str], tmp_path: Path) -> Path:
    """A small tree with the real install.sh and webbundle, a fake uv and a fake npm.

    The fake npm "builds" like Vite: a fresh output directory, so the old stamp is gone.
    """
    root = tmp_path / "checkout"
    (root / "src" / "p11").mkdir(parents=True)
    shutil.copy(ROOT / "install.sh", root)
    for name in ("__init__.py", "webbundle.py"):
        shutil.copy(ROOT / "src" / "p11" / name, root / "src" / "p11")
    (root / "frontend" / "src").mkdir(parents=True)
    (root / "frontend" / "src" / "main.tsx").write_text("one")
    (root / "engine").mkdir()
    for name in ("pyproject.toml", "uv.lock", "engine/engine.lock.toml"):
        (root / name).write_text("")
    bin_dir = tmp_path / "bin"
    fake(
        bin_dir,
        "uv",
        f'echo "uv $*" >> "$FAKE_LOG"\ncase "$*" in *"python find"*) echo {sys.executable};; esac',
    )
    fake(
        bin_dir,
        "npm",
        'echo "npm $* build=${P11_BUILD_ID:-}" >> "$FAKE_LOG"\n'
        'if [[ $* == "run build" ]]; then rm -rf ../src/p11/web; mkdir -p ../src/p11/web; '
        "echo built > ../src/p11/web/index.html; fi",
    )
    fake(bin_dir, "p11", 'echo "p11 $*" >> "$FAKE_LOG"')
    fake(bin_dir, "node", "exit 0")
    return root


def install(root: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    opts = ("--skip-engine", "--no-desktop", "--models", "none", "--yes", *args)
    r = subprocess.run(
        [str(root / "install.sh"), *opts], env=env, capture_output=True, text=True, check=False
    )
    assert r.returncode == 0, r.stdout + r.stderr
    return r


def test_install_builds_a_missing_bundle_then_leaves_it_alone(
    checkout: Path, env: dict[str, str]
) -> None:
    assert "would rebuild the frontend (it has not been built yet)" in (
        install(checkout, env, "--dry-run").stdout
    )
    assert not (checkout / "src/p11/web").exists()
    assert "Rebuilding the Studio frontend (it has not been built yet)" in (
        install(checkout, env).stdout
    )
    log = Path(env["FAKE_LOG"]).read_text()
    assert "npm ci --no-audit --no-fund" in log
    stamp = (checkout / "src/p11/web/build-info.json").read_text()
    assert f"npm run build build={stamp.split(chr(34))[3][:8]}" in log
    second = install(checkout, env)
    assert "Studio frontend is current" in second.stdout and "Rebuilding" not in second.stdout


def test_install_rebuilds_when_the_sources_changed(checkout: Path, env: dict[str, str]) -> None:
    """The update path: `p11 update` checks out a tag, then re-runs install.sh (ADR-0043)."""
    install(checkout, env)
    (checkout / "frontend/src/main.tsx").write_text("two")
    log = Path(env["FAKE_LOG"])
    dry = install(checkout, env, "--dry-run")
    assert "would rebuild the frontend (sources changed since the last build)" in dry.stdout
    log.write_text("")
    r = install(checkout, env)
    assert "Rebuilding the Studio frontend (sources changed since the last build)" in r.stdout
    assert "npm run build" in log.read_text()


def test_install_rebuilds_a_bundle_from_before_the_stamp(
    checkout: Path, env: dict[str, str]
) -> None:
    """Going from v1.0.1 (no stamp) to the first stamped release must rebuild."""
    web = checkout / "src/p11/web"
    web.mkdir()
    (web / "index.html").write_text("old")
    assert "Rebuilding the Studio frontend" in install(checkout, env).stdout
    assert (web / "build-info.json").is_file()


def test_install_keeps_a_prebuilt_tree_without_sources(checkout: Path, env: dict[str, str]) -> None:
    shutil.rmtree(checkout / "frontend")
    r = install(checkout, env)
    assert "no sources in this tree" in r.stdout
    assert "npm" not in Path(env["FAKE_LOG"]).read_text()


def test_install_stops_plainly_when_python_cannot_be_fetched(
    checkout: Path, env: dict[str, str], tmp_path: Path
) -> None:
    """A failed `uv python install` must not run the check with an empty interpreter."""
    fake(tmp_path / "bin", "uv", "exit 1")
    r = subprocess.run(
        [
            str(checkout / "install.sh"),
            "--skip-engine",
            "--no-desktop",
            "--models",
            "none",
            "--yes",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode != 0
    assert "Could not check the Studio frontend build." in r.stderr
    assert "command not found" not in r.stderr


def test_rejects_non_arch(env: dict[str, str], tmp_path: Path) -> None:
    Path(env["P11_OS_RELEASE"]).write_text('ID=ubuntu\nID_LIKE=debian\nPRETTY_NAME="Ubuntu"\n')
    r = run("install.sh", env, "--dry-run")
    assert r.returncode == 3
    assert "not Arch Linux" in r.stderr


def test_missing_nvidia_smi_explains_and_stops(env: dict[str, str], tmp_path: Path) -> None:
    (tmp_path / "bin" / "nvidia-smi").unlink()
    # keep the host's nvidia-smi out of reach: PATH is the fake bin dir plus a minimal system path
    env["PATH"] = f"{tmp_path / 'bin'}:/nonexistent"
    cmds = tmp_path / "bin"
    for tool in ("sed", "tr", "uname", "dirname", "cut", "head", "cat", "sha256sum", "stat"):
        src = subprocess.run(
            ["which", tool], capture_output=True, text=True, check=True
        ).stdout.strip()
        (cmds / tool).symlink_to(src)
    bash = subprocess.run(
        ["which", "bash"], capture_output=True, text=True, check=True
    ).stdout.strip()
    r = subprocess.run(
        [bash, str(ROOT / "install.sh"), "--dry-run"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 3
    assert "never installs drivers" in r.stderr
    assert "wiki.archlinux.org/title/NVIDIA" in r.stderr


def test_old_driver_stops(env: dict[str, str], tmp_path: Path) -> None:
    fake(tmp_path / "bin", "nvidia-smi", 'echo "GeForce GTX 1050, 535.104.05, 4096 MiB"')
    r = run("install.sh", env, "--dry-run")
    assert r.returncode == 3
    assert "too old" in r.stderr


def test_missing_packages_listed_and_never_run_in_dry_run(
    env: dict[str, str], tmp_path: Path
) -> None:
    fake(
        tmp_path / "bin",
        "pacman",
        'case "$1" in -Q) [ "$2" = ffmpeg ] && exit 1; exit 0;; *) exit 1;; esac',
    )
    r = run("install.sh", env, "--dry-run", "--models", "none")
    assert r.returncode == 0
    assert "Missing pacman packages: ffmpeg" in r.stdout
    assert "would run: sudo pacman -S --needed ffmpeg" in r.stdout
    assert not Path(env["FAKE_LOG"]).exists()


def test_missing_packages_without_consent_stop(env: dict[str, str], tmp_path: Path) -> None:
    fake(
        tmp_path / "bin",
        "pacman",
        'case "$1" in -Q) [ "$2" = ffmpeg ] && exit 1; exit 0;; *) exit 1;; esac',
    )
    r = subprocess.run(
        [str(ROOT / "install.sh"), "--models", "none"],
        env=env,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    assert r.returncode == 4
    assert "sudo pacman -S --needed ffmpeg" in r.stderr
    assert not Path(env["FAKE_LOG"]).exists()


def test_pipe_without_tag_is_refused(env: dict[str, str]) -> None:
    script = (ROOT / "install.sh").read_bytes()
    r = subprocess.run(
        ["bash", "-s", "--", "--dry-run"], input=script, env=env, capture_output=True, check=False
    )
    assert r.returncode == 2
    assert b"release tag" in r.stderr


def test_unknown_option(env: dict[str, str]) -> None:
    assert run("install.sh", env, "--bogus").returncode == 2


def test_uninstall_keeps_data_by_default(env: dict[str, str]) -> None:
    home = Path(env["HOME"])
    models = home / ".local/share/p11/models"
    engine = home / ".local/share/p11/engine"
    pics = home / "Pictures/P11"
    conf = home / ".config/p11"
    for d in (models, engine, pics, conf):
        d.mkdir(parents=True)
        (d / "f").write_text("x")
    env = {**env, "XDG_PICTURES_DIR": str(home / "Pictures")}
    r = subprocess.run(
        [str(ROOT / "uninstall.sh"), "--yes"],
        env=env,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert not engine.exists()
    assert models.exists() and pics.exists() and conf.exists()
    assert "Kept:" in r.stdout and "generated images" in r.stdout
    r = subprocess.run(
        [str(ROOT / "uninstall.sh"), "--yes", "--models", "--outputs", "--config"],
        env=env,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    assert r.returncode == 0
    assert not models.exists() and not pics.exists() and not conf.exists()


def test_uninstall_dry_run_removes_nothing(env: dict[str, str]) -> None:
    engine = Path(env["HOME"]) / ".local/share/p11/engine"
    engine.mkdir(parents=True)
    r = run("uninstall.sh", env, "--dry-run", "--yes")
    assert r.returncode == 0 and engine.exists()
