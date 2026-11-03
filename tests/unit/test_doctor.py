"""``p11 doctor``: each check, with fakes for nvidia-smi, the engine and the models root."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from p11 import doctor
from p11.cli import app
from p11.config import load_settings
from p11.doctor import Report

runner = CliRunner()
ROOT = Path(__file__).resolve().parents[2]


def completed(stdout: str = "", code: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr="")


def codes(report: Report) -> set[str]:
    return {p.code for p in report.problems}


def test_gpu_present_missing_and_broken(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda n: None)
    r = Report()
    doctor.check_gpu(r)
    assert codes(r) == {"gpu.missing"} and "never installs drivers" in r.problems[0].hint
    monkeypatch.setattr(doctor.shutil, "which", lambda n: "/usr/bin/nvidia-smi")
    r = Report()
    doctor.check_gpu(
        r, run=lambda a, t: completed("NVIDIA GeForce RTX 2070, 615.78.08, 8192 MiB\n")
    )
    assert r.ok and "RTX 2070" in r.checks[0].detail and "615.78.08" in r.checks[0].detail
    r = Report()
    doctor.check_gpu(r, run=lambda a, t: completed("", 9))
    assert codes(r) == {"gpu.unavailable"}


def _engine(tmp_path: Path, version: str = "0.43.0") -> Path:
    eng = tmp_path / "data" / "engine"
    (eng / "venv" / "bin").mkdir(parents=True)
    (eng / "venv" / "bin" / "python").write_text("")
    (eng / "ComfyUI").mkdir()
    (eng / "ComfyUI" / "comfyui_version.py").write_text(f'__version__ = "{version}"\n')
    return eng


TORCH_OK = json.dumps({"torch": "2.14.1+cu130", "cuda": True, "capability": [7, 5],
                       "arch": ["sm_75", "sm_80"]})  # fmt: skip


def test_engine_missing(tmp_path):
    r = Report()
    doctor.check_engine(r, quick=True)
    assert codes(r) == {"engine.missing"}


def test_engine_pinned_and_torch_ok(tmp_path):
    _engine(tmp_path)
    r = Report()
    doctor.check_engine(r, run=lambda a, t: completed(TORCH_OK))
    assert r.ok and not r.problems, r.problems
    assert {c.name for c in r.checks} == {"engine", "torch"}


def test_engine_version_mismatch(tmp_path):
    _engine(tmp_path, "0.40.0")
    r = Report()
    doctor.check_engine(r, quick=True)
    assert codes(r) == {"engine.version"} and "engine_setup.sh" in r.problems[0].hint


@pytest.mark.parametrize(
    ("out", "code", "expect"),
    [
        ("", 1, "engine.torch"),
        ("garbage", 0, "engine.torch"),
        (json.dumps({"torch": "2.14.1+cu130", "cuda": False, "capability": None, "arch": []}), 0,
         "engine.cuda"),
        (json.dumps({"torch": "2.14.1+cu130", "cuda": True, "capability": [7, 5],
                     "arch": ["sm_90"]}), 0, "engine.arch"),
        (json.dumps({"torch": "2.9.0", "cuda": True, "capability": [7, 5], "arch": ["sm_75"]}), 0,
         "engine.torch-version"),
    ],
)  # fmt: skip
def test_torch_problems(tmp_path, out, code, expect):
    _engine(tmp_path)
    r = Report()
    doctor.check_engine(r, run=lambda a, t: completed(out, code))
    assert expect in codes(r)


def test_engine_lock_unreadable(tmp_path, monkeypatch):
    bad = tmp_path / "lock.toml"
    bad.write_text("[nothing]\n")
    monkeypatch.setenv("P11_ENGINE_LOCK", str(bad))
    r = Report()
    doctor.check_engine(r, quick=True)
    assert codes(r) == {"engine.lock"}


def test_models_renamed_away_gives_an_actionable_hint(tmp_path, monkeypatch):
    models = tmp_path / "models"
    monkeypatch.setenv("P11_MODELS_ROOT", str(models))
    r = Report()
    doctor.check_models(r)
    missing = [p for p in r.problems if p.code == "models.missing-default"]
    assert len(missing) == 4  # empty root: every default model is missing
    assert all("p11 models install default" in p.hint for p in missing)


def test_ports_and_disk_and_permissions(tmp_path, monkeypatch):
    settings = load_settings()
    monkeypatch.setattr(doctor, "port_in_use", lambda h, p: p == settings.engine_port)
    r = Report()
    doctor.check_ports(r, settings)
    assert codes(r) == {"ports.engine"}
    monkeypatch.setattr(doctor, "port_in_use", lambda h, p: p == settings.studio_port)
    r = Report()
    doctor.check_ports(r, settings)
    assert codes(r) == {"ports.studio"}
    r = Report()
    doctor.check_disk(r, settings, free=lambda p: 10**9)
    assert codes(r) == {"disk.outputs"}
    r = Report()
    doctor.check_disk(r, settings, free=lambda p: 10**12)
    assert not r.problems
    loose = tmp_path / "data"
    loose.mkdir()
    loose.chmod(0o755)
    r = Report()
    doctor.check_permissions(r, settings)
    assert codes(r) == {"permissions"} and f"chmod 700 '{loose}'" in r.problems[0].hint
    loose.chmod(0o700)
    r = Report()
    doctor.check_permissions(r, settings)
    assert not r.problems


def test_doctor_cli_json_and_exit_code(monkeypatch):
    rep = Report()
    rep.checks.append(doctor.Check("gpu", "fine"))
    monkeypatch.setattr(doctor, "run_checks", lambda quick=False: rep)
    r = runner.invoke(app, ["doctor"])
    assert r.exit_code == 0 and "All good." in r.output
    from p11.problems import Problem

    rep.problems.append(Problem("warning", "x.warn", "Something odd.", "Do a thing."))
    r = runner.invoke(app, ["doctor"])
    assert r.exit_code == 0 and "with warnings" in r.output and "→ Do a thing." in r.output
    rep.problems.append(Problem("error", "x.err", "Broken.", "Fix it."))
    r = runner.invoke(app, ["doctor", "--json"])
    assert r.exit_code == 1
    assert json.loads(r.output)["ok"] is False


def test_run_checks_never_raises(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda n: None)
    report = doctor.run_checks(quick=True)
    assert "gpu.missing" in codes(report) and "engine.missing" in codes(report)
