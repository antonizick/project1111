"""Starter templates (Phase 09): bundled recipes installed into the user's store on first run.

``templates/starter/*.json`` in the repo (override with ``$P11_STARTER_TEMPLATES``). A marker file
in the template store remembers which starter IDs were installed, so a starter the user deleted or
edited is never put back or overwritten.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from ..recipe.migrate import RecipeFormatError, RecipeVersionError, loads
from .store import TemplateStore

log = logging.getLogger("p11.templates")
MARKER = ".starter-installed.json"


def find_starter_dir() -> Path:
    override = os.environ.get("P11_STARTER_TEMPLATES")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "templates" / "starter"


def install_starters(store: TemplateStore, source: Path | None = None) -> list[str]:
    """Install starters not installed before; returns the IDs added this time."""
    source = source or find_starter_dir()
    if not source.is_dir():
        return []
    marker = store.root / MARKER
    try:
        done = set(json.loads(marker.read_text())) if marker.is_file() else set()
    except (OSError, ValueError):
        done = set()
    added: list[str] = []
    for path in sorted(source.glob("*.json")):
        try:
            recipe = loads(path.read_bytes())
        except (OSError, RecipeFormatError, RecipeVersionError) as exc:
            log.warning("skipping starter template %s: %s", path.name, exc)
            continue
        if recipe.id in done:
            continue
        if store.find(recipe.id) is None:
            store.save(recipe)
            added.append(recipe.id)
        done.add(recipe.id)
    if added or not marker.exists():
        store.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        marker.write_text(json.dumps(sorted(done)) + "\n")
    return added
