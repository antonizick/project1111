"""The Studio bundle's build stamp and the stale check (ADR-0043)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from p11 import __version__, webbundle


@pytest.fixture
def tree(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    (root / "frontend" / "src" / "app").mkdir(parents=True)
    (root / "frontend" / "src" / "main.tsx").write_text("main")
    (root / "frontend" / "src" / "app" / "Shell.tsx").write_text("shell")
    (root / "frontend" / "index.html").write_text("<html>")
    (root / "frontend" / "package-lock.json").write_text("{}")
    (root / "frontend" / "vite.config.ts").write_text("config")
    web = root / "src" / "p11" / "web"
    web.mkdir(parents=True)
    (web / "index.html").write_text("built")
    return root, web


def test_hash_is_stable_and_follows_every_input(tree):
    root, _ = tree
    first = webbundle.source_hash(root)
    assert webbundle.source_hash(root) == first
    for rel in ("src/main.tsx", "index.html", "package-lock.json", "vite.config.ts"):
        path = root / "frontend" / rel
        before = path.read_text()
        path.write_text(before + "!")
        assert webbundle.source_hash(root) != first, rel
        path.write_text(before)
    assert webbundle.source_hash(root) == first
    public = root / "frontend" / "public"
    public.mkdir()
    (public / "icon.svg").write_text("<svg/>")
    assert webbundle.source_hash(root) != first


def test_hash_is_path_prefixed_and_ignores_other_files(tree):
    root, _ = tree
    first = webbundle.source_hash(root)
    src = root / "frontend" / "src"
    (src / "main.tsx").rename(src / "moved.tsx")
    assert webbundle.source_hash(root) != first
    (src / "moved.tsx").rename(src / "main.tsx")
    assert webbundle.source_hash(root) == first
    (src / "node_modules").mkdir()
    (src / "node_modules" / "dep.js").write_text("dep")
    (root / "frontend" / "node_modules").mkdir()
    (root / "frontend" / "README.md").write_text("not an input")
    assert webbundle.source_hash(root) == first


def test_status_current_stale_missing_and_no_sources(tree, tmp_path):
    root, web = tree
    assert webbundle.status(root, web) == "stale"  # a bundle with no stamp: built by an older P11
    stamp = webbundle.write_stamp(root, web)
    assert webbundle.status(root, web) == "current"
    assert webbundle.build_id(web) == stamp["source_hash"][:8]
    (root / "frontend" / "src" / "main.tsx").write_text("changed")
    assert webbundle.status(root, web) == "stale"
    (web / "index.html").unlink()
    assert webbundle.status(root, web) == "missing"
    assert webbundle.status(tmp_path / "installed", web) == "no-sources"


def test_unreadable_stamp_counts_as_none(tree):
    root, web = tree
    (web / webbundle.STAMP).write_text("{not json")
    assert webbundle.read_stamp(web) is None and webbundle.build_id(web) is None
    assert webbundle.status(root, web) == "stale"


def test_stamp_contents_carry_no_paths(tree):
    root, web = tree
    stamp = json.loads(json.dumps(webbundle.write_stamp(root, web)))
    assert set(stamp) == {"source_hash", "built_at", "version", "commit"}
    assert stamp["version"] == __version__
    assert str(root) not in (web / webbundle.STAMP).read_text()


def test_build_bakes_the_id_in_then_stamps(tree, monkeypatch):
    root, web = tree
    seen: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        if argv[0] == "npm":
            seen.update(argv=argv, cwd=kwargs["cwd"], build=kwargs["env"]["P11_BUILD_ID"])
        return subprocess.CompletedProcess(argv, 0, stdout="abc1234\n")

    monkeypatch.setattr(webbundle.subprocess, "run", fake_run)
    webbundle.build(root, web)
    assert seen["argv"] == ["npm", "run", "build"] and seen["cwd"] == root / "frontend"
    assert seen["build"] == webbundle.build_id(web)
    assert webbundle.status(root, web) == "current"


def test_module_runs_with_the_standard_library_alone():
    """install.sh runs it on a bare uv Python, before P11's environment exists."""
    src = Path(webbundle.__file__).resolve().parents[1]
    r = subprocess.run(
        [sys.executable, "-S", "-m", "p11.webbundle", "status"],
        env={**os.environ, "PYTHONPATH": str(src)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() in ("current", "stale", "missing", "no-sources")


def test_main_refuses_unknown_commands(capsys):
    assert webbundle.main(["nope"]) == 2
    assert "usage" in capsys.readouterr().err
