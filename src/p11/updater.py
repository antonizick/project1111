"""``p11 update`` and ``p11 uninstall``: tag-based updates of the checkout the app runs from."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


class UpdateError(Exception):
    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


def repo_root() -> Path:
    """The checkout this install runs from (the editable install points at it)."""
    root = Path(__file__).resolve().parents[2]
    if not (root / "install.sh").is_file():
        raise UpdateError(
            "P11 was not installed from a git checkout, so it cannot update itself.",
            "Clone the repository and run ./install.sh.",
        )
    return root


def tag_key(tag: str) -> tuple[int, int, int] | None:
    m = TAG_RE.match(tag)
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def release_tags(tags: list[str]) -> list[str]:
    """Release tags (``vX.Y.Z``) sorted oldest to newest; pre-releases and others are ignored."""
    keyed = [(k, t) for t in tags if (k := tag_key(t)) is not None]
    return [t for _, t in sorted(keyed)]


def _git(root: Path, *args: str) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UpdateError(f"git failed: {exc}", "Is git installed?") from exc
    if r.returncode != 0:
        raise UpdateError(f"git {args[0]} failed: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


def local_modifications(root: Path) -> list[str]:
    """Tracked files with local changes (untracked and ignored files do not block an update)."""
    return [ln for ln in _git(root, "status", "--porcelain", "--untracked-files=no").splitlines()]


def current_version(root: Path) -> str:
    return _git(root, "describe", "--tags", "--always").strip()


@dataclass(frozen=True)
class Plan:
    current: str
    target: str | None
    changelog: str
    up_to_date: bool


def plan_update(root: Path, to: str | None = None, *, fetch: bool = True) -> Plan:
    """Decide the target tag and collect the CHANGELOG diff; refuses a modified checkout."""
    dirty = local_modifications(root)
    if dirty:
        raise UpdateError(
            f"The checkout has local modifications ({len(dirty)} file(s)): {dirty[0].strip()}.",
            "Commit, stash or discard them, then run `p11 update` again.",
        )
    if fetch:
        _git(root, "fetch", "--tags", "--force", "--quiet", "origin")
    current = current_version(root)
    tags = release_tags(_git(root, "tag", "--list").split())
    if to is not None:
        if to not in tags:
            raise UpdateError(
                f"There is no release tag {to}.", f"Available: {', '.join(tags) or 'none'}."
            )
        target = to
    elif tags:
        target = tags[-1]
    else:
        return Plan(current, None, "", True)
    at_target = (
        _git(root, "rev-parse", "HEAD").strip()
        == _git(root, "rev-parse", f"{target}^{{commit}}").strip()
    )
    changelog = "" if at_target else _git(root, "diff", "HEAD", target, "--", "CHANGELOG.md")
    return Plan(current, target, changelog, at_target)


def checkout(root: Path, tag: str) -> None:
    _git(root, "-c", "advice.detachedHead=false", "checkout", "--quiet", tag)
