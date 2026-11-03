"""Recipe schema migrations (ADR-0007): old template JSON is upgraded step by step, never guessed.

``MIGRATIONS[n]`` turns a version-``n`` dict into a version-``n + 1`` dict. v1 is the first schema,
so the chain is empty today; the next schema change adds ``MIGRATIONS[1]`` and a test for it.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from pydantic import ValidationError

from .model import SCHEMA_VERSION, Recipe

Migration = Callable[[dict[str, Any]], dict[str, Any]]

MIGRATIONS: dict[int, Migration] = {}


class RecipeVersionError(ValueError):
    """The recipe's ``schema_version`` is missing, invalid, or newer than this P11 understands."""


class RecipeFormatError(ValueError):
    """The data is not a valid recipe; the message lists the problems in plain English."""


def schema_version_of(data: Mapping[str, Any]) -> int:
    version = data.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise RecipeVersionError("This is not a P11 recipe: it has no whole-number schema_version.")
    if version < 1:
        raise RecipeVersionError(f"Recipe schema version {version} is not valid.")
    if version > SCHEMA_VERSION:
        raise RecipeVersionError(
            f"This recipe uses schema version {version}, but this P11 understands up to "
            f"{SCHEMA_VERSION}. Update P11 to open it."
        )
    return version


def upgrade(data: Mapping[str, Any], target: int = SCHEMA_VERSION) -> dict[str, Any]:
    """Apply migrations until ``data`` is at ``target``; the input is not modified."""
    # A deep copy, which also proves the data is plain JSON.
    out: dict[str, Any] = json.loads(json.dumps(data))
    version = schema_version_of(out)
    while version < target:
        step = MIGRATIONS.get(version)
        if step is None:
            raise RecipeVersionError(f"No migration from recipe schema version {version}.")
        out = step(out)
        new_version = out.get("schema_version")
        if new_version != version + 1:
            raise RecipeVersionError(
                f"Migration from version {version} produced version {new_version!r}."
            )
        version = new_version
    return out


def migrate(data: Mapping[str, Any]) -> Recipe:
    """Upgrade ``data`` to the current schema and validate it."""
    upgraded = upgrade(data)
    try:
        return Recipe.model_validate(upgraded)
    except ValidationError as exc:
        raise RecipeFormatError(_explain(exc)) from exc


def loads(text: str | bytes) -> Recipe:
    """Parse recipe JSON of any supported version."""
    try:
        data = json.loads(text)
    except (ValueError, UnicodeDecodeError) as exc:
        raise RecipeFormatError(f"This is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise RecipeFormatError("A recipe must be a JSON object.")
    return migrate(data)


def _explain(exc: ValidationError) -> str:
    lines = []
    for err in exc.errors(include_url=False)[:10]:
        loc = ".".join(str(p) for p in err["loc"]) or "recipe"
        lines.append(f"{loc}: {err['msg']}")
    more = exc.error_count() - len(lines)
    if more > 0:
        lines.append(f"... and {more} more")
    return "This recipe is not valid. " + "; ".join(lines)
