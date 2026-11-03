from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from p11 import cli, updater

runner = CliRunner()


def git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repos(tmp_path: Path) -> tuple[Path, Path]:
    origin, clone = tmp_path / "origin", tmp_path / "clone"
    origin.mkdir()
    git(origin, "init", "-q", "-b", "main")
    (origin / "CHANGELOG.md").write_text("# Changelog\n")
    git(origin, "add", ".")
    git(origin, "commit", "-qm", "one")
    git(origin, "tag", "v0.1.0")
    git(tmp_path, "clone", "-q", str(origin), str(clone))
    (origin / "CHANGELOG.md").write_text("# Changelog\n## 0.2.0\n- new thing\n")
    git(origin, "commit", "-qam", "two")
    git(origin, "tag", "v0.2.0")
    git(origin, "tag", "v0.3.0-rc1")
    return origin, clone


def test_release_tags_sorted_and_filtered() -> None:
    tags = ["v0.10.0", "v0.2.0", "v1.0.0-rc1", "latest", "v0.2.1"]
    assert updater.release_tags(tags) == ["v0.2.0", "v0.2.1", "v0.10.0"]


def test_plan_picks_latest_and_shows_changelog(repos: tuple[Path, Path]) -> None:
    _, clone = repos
    plan = updater.plan_update(clone)
    assert plan.target == "v0.2.0"
    assert not plan.up_to_date
    assert "+- new thing" in plan.changelog


def test_plan_refuses_local_modifications(repos: tuple[Path, Path]) -> None:
    _, clone = repos
    (clone / "CHANGELOG.md").write_text("edited\n")
    with pytest.raises(updater.UpdateError, match="local modifications"):
        updater.plan_update(clone)


def test_untracked_files_do_not_block(repos: tuple[Path, Path]) -> None:
    _, clone = repos
    (clone / "scratch.txt").write_text("x")
    assert updater.plan_update(clone).target == "v0.2.0"


def test_to_unknown_tag(repos: tuple[Path, Path]) -> None:
    _, clone = repos
    with pytest.raises(updater.UpdateError, match="no release tag"):
        updater.plan_update(clone, "v9.9.9")


def test_checkout_then_up_to_date(repos: tuple[Path, Path]) -> None:
    _, clone = repos
    updater.plan_update(clone)  # fetches the tags
    updater.checkout(clone, "v0.2.0")
    assert updater.plan_update(clone).up_to_date


def test_cli_update_dry_run(repos: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    _, clone = repos
    monkeypatch.setattr(updater, "repo_root", lambda: clone)
    result = runner.invoke(cli.app, ["update", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "v0.2.0" in result.output
    assert "Dry run" in result.output
    assert updater.current_version(clone).startswith("v0.1.0")


def test_cli_update_without_checkout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def boom() -> Path:
        raise updater.UpdateError("no checkout", "clone it")

    monkeypatch.setattr(updater, "repo_root", boom)
    result = runner.invoke(cli.app, ["update"])
    assert result.exit_code == 1
