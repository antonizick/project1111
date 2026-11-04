"""Is the built Studio bundle the build of this checkout's frontend sources? (ADR-0043)

``src/p11/web`` is git-ignored, so a merge or a checkout changes the sources under a bundle that
stays as it was. ``build-info.json`` in the bundle records a hash of the sources it was built from.
Standard library only: ``install.sh`` runs this before P11's own environment exists. Nothing here
runs from ``p11 serve``, which must not need npm.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Literal

from p11 import __version__

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = Path(__file__).resolve().parent / "web"
STAMP = "build-info.json"
#: Length of the build id shown by the Studio, ``p11 status`` and ``/healthz``.
ID_LENGTH = 8
FRONTEND_FILES = ("index.html", "package-lock.json", "vite.config.ts")
FRONTEND_TREES = ("src", "public")
REBUILD_HINT = "Run `make build` (or `./install.sh`), then `p11 stop && p11 start`."

Status = Literal["current", "stale", "missing", "no-sources"]


def source_files(root: Path) -> list[Path]:
    """The frontend inputs that exist, sorted by repo-relative path."""
    frontend = root / "frontend"
    found = [frontend / name for name in FRONTEND_FILES]
    for tree in FRONTEND_TREES:
        found += (frontend / tree).rglob("*")
    keep = [p for p in found if p.is_file() and "node_modules" not in p.parts]
    return sorted(keep, key=lambda p: p.relative_to(root).as_posix())


def source_hash(root: Path) -> str:
    """SHA-256 over every input's relative path and content."""
    digest = hashlib.sha256()
    for path in source_files(root):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def read_stamp(web_dir: Path = WEB_DIR) -> dict[str, str] | None:
    try:
        stamp = json.loads((web_dir / STAMP).read_text())
    except (OSError, ValueError):
        return None
    return stamp if isinstance(stamp, dict) and "source_hash" in stamp else None


def build_id(web_dir: Path = WEB_DIR) -> str | None:
    """The short id of the bundle on disk; None for no bundle or an unstamped one."""
    stamp = read_stamp(web_dir)
    return stamp["source_hash"][:ID_LENGTH] if stamp else None


def _git_commit(root: Path) -> str | None:
    try:
        r = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() or None if r.returncode == 0 else None


def write_stamp(root: Path = REPO_ROOT, web_dir: Path = WEB_DIR) -> dict[str, str | None]:
    stamp = {
        "source_hash": source_hash(root),
        "built_at": time.strftime("%Y-%m-%d %H:%M %Z"),
        "version": __version__,
        "commit": _git_commit(root),
    }
    (web_dir / STAMP).write_text(json.dumps(stamp, indent=2) + "\n")
    return stamp


def status(root: Path = REPO_ROOT, web_dir: Path = WEB_DIR) -> Status:
    """``stale`` includes a bundle with no stamp: nothing says what it was built from."""
    if not (root / "frontend" / "src").is_dir():
        return "no-sources"
    if not (web_dir / "index.html").is_file():
        return "missing"
    stamp = read_stamp(web_dir)
    return "current" if stamp and stamp["source_hash"] == source_hash(root) else "stale"


def build(root: Path = REPO_ROOT, web_dir: Path = WEB_DIR) -> None:
    """``npm run build`` with the id baked in (so a window shows what it loaded), then the stamp."""
    env = {**os.environ, "P11_BUILD_ID": source_hash(root)[:ID_LENGTH]}
    subprocess.run(["npm", "run", "build"], cwd=root / "frontend", env=env, check=True)
    write_stamp(root, web_dir)


def main(argv: list[str]) -> int:
    command = argv[0] if len(argv) == 1 else ""
    if command == "status":
        print(status())
    elif command == "id":
        print(build_id() or "")
    elif command == "build":
        build()
    else:
        print("usage: python -m p11.webbundle status|id|build", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
