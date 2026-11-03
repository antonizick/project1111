import functools
import json
import pickle

import pytest
from tests.fixtures.model_server import safetensors_bytes, serve
from tests.unit.test_models_registry import CKPT, manifest_text
from typer.testing import CliRunner

from p11.cli import app
from p11.models import cli as models_cli
from p11.models.download import Downloader
from p11.models.manifest import parse_manifest
from p11.models.registry import ModelManager

runner = CliRunner()


@pytest.fixture
def server():
    yield from serve()


@pytest.fixture
def root(server, tmp_path, monkeypatch):
    root = tmp_path / "models"
    manifest = parse_manifest(manifest_text(server), loopback_http=True)
    monkeypatch.setattr(models_cli, "_manager", lambda: ModelManager(root, manifest))
    monkeypatch.setattr(
        models_cli,
        "Downloader",
        functools.partial(Downloader, insecure_hosts=["127.0.0.1"], sleep=lambda s: None),
    )
    return root


def run(*args):
    return runner.invoke(app, ["models", *args])


def norm(text, root):
    return json.loads(text.replace(str(root), "<root>"))


def test_list_json_snapshot(root):
    r = run("list", "--json")
    assert r.exit_code == 0, r.output
    data = norm(r.stdout, root)
    assert data["models_root"] == "<root>"
    assert [(m["id"], m["state"], m["sets"]) for m in data["models"]] == [
        ("ckpt", "missing", ["default"]),
        ("vae", "missing", ["default", "full"]),
        ("up", "missing", ["full"]),
    ]
    assert data["models"][2]["licence"] == {
        "name": "CC-BY-NC-4.0",
        "url": "https://example.org/nc",
        "commercial_use": False,
        "flags": ["non-commercial", "attribution"],
        "accepted": False,
    }
    assert set(data["models"][0]) == {
        "id", "name", "kind", "base", "state", "origin", "filename", "path", "size", "sha256",
        "verified", "enabled", "sets", "format", "licence", "detail",
    }  # fmt: skip


def test_install_flow_json(root, tmp_path):
    r = run("install", "default", "--json")
    assert r.exit_code == 1
    assert "accept-licences" in json.loads(r.stdout)["error"]
    r = run("install", "default", "--dry-run", "--json")
    assert json.loads(r.stdout) == {
        "models": ["ckpt", "vae"],
        "to_fetch": ["ckpt", "vae"],
        "licences_to_accept": ["ckpt"],
        "total_bytes": json.loads(r.stdout)["total_bytes"],
        "download_bytes": json.loads(r.stdout)["total_bytes"],
    }
    assert "2 model(s)" in r.stderr
    r = run("install", "default", "--accept-licences", "--json")
    assert r.exit_code == 0, r.output
    report = json.loads(r.stdout)
    assert report["downloaded"] == ["ckpt", "vae"] and report["licences_accepted"] == ["ckpt"]
    r = run("install", "default", "--json")
    assert json.loads(r.stdout)["downloaded"] == [] and json.loads(r.stdout)["present"] == [
        "ckpt",
        "vae",
    ]
    r = run("install", "default")
    assert "0 downloaded" in r.stdout and "2 already present" in r.stdout


def test_install_text_progress(root):
    r = run("install", "vae")
    assert r.exit_code == 0, r.output
    assert "vae: 100 %" in r.stderr and "1 downloaded" in r.stdout


def test_install_writes_engine_config(root, tmp_path):
    (tmp_path / "data" / "engine").mkdir(parents=True)
    r = run("install", "vae")
    assert "extra_model_paths.yaml" in r.stderr
    assert str(root) in (tmp_path / "data" / "engine" / "extra_model_paths.yaml").read_text()


def test_verify_detects_corruption(root):
    run("install", "default", "--accept-licences")
    r = run("verify", "--json")
    assert r.exit_code == 0 and json.loads(r.stdout)["ok"]
    (root / "checkpoints" / "ckpt.safetensors").write_bytes(b"\0" * len(CKPT))
    r = run("verify")
    assert r.exit_code == 1
    assert "BAD ckpt: corrupt" in r.stdout and "OK  vae" in r.stdout
    r = run("verify", "vae", "--json")
    assert r.exit_code == 0


def test_verify_nothing_installed(root):
    r = run("verify")
    assert r.exit_code == 0 and "No installed models" in r.stdout


def test_list_text_and_set_filter(root):
    run("install", "vae")
    run("disable", "vae")
    r = run("list", "--set", "full")
    assert r.exit_code == 0
    assert "installed*" in r.stdout and "* disabled" in r.stdout and "NON-COMMERCIAL" in r.stdout
    assert "ckpt " in r.stdout  # full includes default


def test_add_remove_enable(root, tmp_path):
    src = tmp_path / "MyLora.safetensors"
    src.write_bytes(safetensors_bytes({"lora_unet_a.lora_up.weight": 4, "lora_te2_x.alpha": 1}))
    r = run("add", str(src), "--json")
    assert r.exit_code == 0, r.output
    added = norm(r.stdout, root)
    assert (added["id"], added["kind"], added["base"], added["state"]) == (
        "mylora",
        "lora",
        "sdxl",
        "user-added",
    )
    assert run("disable", "mylora", "--json").stdout.strip().startswith("{")
    assert "mylora enabled" in run("enable", "mylora").stdout
    r = run("remove", "mylora", "--json")
    assert "left in place" in json.loads(r.stdout)["message"]


def test_add_pickle_refused_then_allowed(root, tmp_path):
    src = tmp_path / "evil.ckpt"
    src.write_bytes(pickle.dumps({"a": 1}))
    r = run("add", str(src), "--kind", "checkpoint")
    assert r.exit_code == 1 and "--allow-pickle" in r.stderr
    r = run("add", str(src), "--kind", "checkpoint", "--allow-pickle")
    assert r.exit_code == 0 and "arbitrary code" in r.stderr


def test_remove_needs_yes_for_a_file(root):
    run("install", "vae")
    r = run("remove", "vae")
    assert r.exit_code == 1 and "--yes" in r.stderr
    r = run("remove", "vae", "--yes")
    assert r.exit_code == 0 and "Deleted" in r.stdout


def test_licences(root):
    run("install", "up", "--accept-licences")
    r = run("licences", "--json")
    rows = {x["id"]: x for x in json.loads(r.stdout)["licences"]}
    assert rows["up"]["accepted_at"] and not rows["up"]["commercial_use"]
    assert rows["vae"]["needs_acknowledgement"] is False
    text = run("licences").stdout
    assert "commercial: NO" in text and "no acknowledgement needed" in text
    assert "not accepted yet" in text


def test_unknown_model_errors(root):
    r = run("enable", "nope")
    assert r.exit_code == 1 and "No model 'nope'" in r.stderr
    r = run("install", "nope", "--json")
    assert "neither a set" in json.loads(r.stdout)["error"]


def test_real_manifest_through_cli(tmp_path, monkeypatch):
    """No patching: the shipped manifest and an empty models root."""
    monkeypatch.setenv("P11_MODELS_ROOT", str(tmp_path / "empty"))
    r = runner.invoke(app, ["models", "install", "default", "--dry-run", "--json"])
    assert r.exit_code == 0, r.output
    data = json.loads(r.stdout)
    assert data["total_bytes"] == data["download_bytes"] == 14_631_650_390
