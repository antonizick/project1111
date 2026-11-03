import json
from typing import Any

import pytest
from tests.helpers import recipe

from p11.recipe import migrate as m
from p11.recipe.migrate import (
    RecipeFormatError,
    RecipeVersionError,
    loads,
    migrate,
    schema_version_of,
    upgrade,
)
from p11.recipe.model import SCHEMA_VERSION


def _data() -> dict[str, Any]:
    return json.loads(recipe().to_json())  # type: ignore[no-any-return]


def test_current_version_passes_through() -> None:
    data = _data()
    assert migrate(data) == recipe()
    assert upgrade(data) == data
    assert upgrade(data) is not data


@pytest.mark.parametrize("bad", [None, "1", 1.0, True])
def test_missing_or_non_integer_version(bad: object) -> None:
    data = _data()
    data["schema_version"] = bad
    with pytest.raises(RecipeVersionError, match="schema_version"):
        migrate(data)


def test_missing_version_key() -> None:
    data = _data()
    del data["schema_version"]
    with pytest.raises(RecipeVersionError):
        migrate(data)


def test_zero_version_invalid() -> None:
    with pytest.raises(RecipeVersionError, match="not valid"):
        schema_version_of({"schema_version": 0})


def test_future_version_refused_clearly() -> None:
    data = _data()
    data["schema_version"] = SCHEMA_VERSION + 1
    with pytest.raises(RecipeVersionError, match="Update P11"):
        migrate(data)


def test_migration_chain_runs_each_step(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate schema v3: a v1 recipe walks v1→v2→v3 through each registered migration."""
    calls: list[int] = []

    def v1_to_v2(d: dict[str, Any]) -> dict[str, Any]:
        calls.append(1)
        d["legacy_title"] = d.pop("name")
        return {**d, "schema_version": 2}

    def v2_to_v3(d: dict[str, Any]) -> dict[str, Any]:
        calls.append(2)
        d["name"] = d.pop("legacy_title").upper()
        return {**d, "schema_version": 3}

    monkeypatch.setattr(m, "MIGRATIONS", {1: v1_to_v2, 2: v2_to_v3})
    monkeypatch.setattr(m, "SCHEMA_VERSION", 3)
    out = upgrade(_data(), target=3)
    assert calls == [1, 2]
    assert out["schema_version"] == 3 and out["name"] == "TEST RECIPE"


def test_missing_migration_step(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(m, "SCHEMA_VERSION", 2)
    monkeypatch.setattr(m, "MIGRATIONS", {})
    with pytest.raises(RecipeVersionError, match="No migration from recipe schema version 1"):
        upgrade(_data(), target=2)


def test_migration_must_bump_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(m, "SCHEMA_VERSION", 2)
    monkeypatch.setattr(m, "MIGRATIONS", {1: lambda d: d})
    with pytest.raises(RecipeVersionError, match="produced version 1"):
        upgrade(_data(), target=2)


def test_invalid_recipe_explained() -> None:
    data = _data()
    data["steps"] = []
    data["name"] = ""
    with pytest.raises(RecipeFormatError, match="not valid") as exc:
        migrate(data)
    assert "steps" in str(exc.value) and "name" in str(exc.value)


def test_loads_rejects_non_json_and_non_objects() -> None:
    with pytest.raises(RecipeFormatError, match="not valid JSON"):
        loads("{nope")
    with pytest.raises(RecipeFormatError, match="JSON object"):
        loads("[1, 2]")
    with pytest.raises(RecipeFormatError):
        loads(b"\xff\xfe")


def test_explain_truncates_long_error_lists() -> None:
    data = _data()
    data["steps"] = [{"type": "generate"} for _ in range(12)]
    with pytest.raises(RecipeFormatError, match="more"):
        migrate(data)
