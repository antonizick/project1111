"""install.sh / uninstall.sh with a fake os-release, nvidia-smi and pacman (no root, no GPU)."""

from __future__ import annotations

import os
import stat
import subprocess
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
