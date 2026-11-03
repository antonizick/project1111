import json
import stat
from pathlib import Path

import pytest
from tests.helpers import recipe

from p11.recipe.model import SCHEMA_VERSION
from p11.templates.store import TemplateError, TemplateStore, folder_path


def store(tmp_path: Path) -> TemplateStore:
    return TemplateStore(tmp_path / "templates")


def test_save_load_list(tmp_path: Path) -> None:
    s = store(tmp_path)
    r = recipe(name="Software Logo Dark", folder="Logos/Dark", tags=("logo", "dark"))
    info = s.save(r)
    assert info.path == tmp_path / "templates" / "logos" / "dark" / "software-logo-dark.json"
    assert stat.S_IMODE(info.path.stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "templates" / "logos").stat().st_mode) == 0o700
    assert s.load("Logos/Dark", "software-logo-dark") == r
    assert [t.recipe for t in s.all()] == [r]
    assert s.folders() == ["logos/dark"]


def test_same_id_overwrites_other_id_gets_suffix(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.save(recipe(id="a", name="Avatar"))
    s.save(recipe(id="a", name="Avatar", tags=("v2",)))
    s.save(recipe(id="b", name="Avatar"))
    names = sorted(p.name for p in (tmp_path / "templates").glob("*.json"))
    assert names == ["avatar-2.json", "avatar.json"]
    assert s.find("a").recipe.tags == ("v2",)  # type: ignore[union-attr]


def test_moving_folder(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.save(recipe(id="a", name="X"))
    s.save(recipe(id="a", name="X", folder="New"))
    assert [t.folder for t in s.all()] == ["new"]


def test_search_by_name_tag_folder(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.save(recipe(id="1", name="Software Logo Dark", tags=("logo",), folder="Brand"))
    s.save(recipe(id="2", name="Pixel Avatar", tags=("avatar", "Fun")))
    s.save(recipe(id="3", name="Wallpaper Lake"))
    assert [t.recipe.id for t in s.search("logo")] == ["1"]
    assert [t.recipe.id for t in s.search("brand dark")] == ["1"]
    assert [t.recipe.id for t in s.search(tag="fun")] == ["2"]
    assert [t.recipe.id for t in s.search("lake", tag="fun")] == []
    assert len(s.search()) == 3


def test_export_import(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.save(recipe(id="orig", name="Lake"))
    data = s.export("orig")
    assert json.loads(data)["schema_version"] == SCHEMA_VERSION
    imported = s.import_bytes(data)
    assert imported.recipe.id != "orig" and imported.path.name == "lake-2.json"
    same = s.import_bytes(data, keep_id=True)
    assert same.recipe.id == "orig" and same.path.name == "lake.json"
    with pytest.raises(TemplateError, match="No template"):
        s.export("missing")


@pytest.mark.parametrize(
    ("data", "msg"),
    [
        (b"{nope", "not valid JSON"),
        (b'{"schema_version": 99}', "Update P11"),
        (b'{"schema_version": 1, "name": "x"}', "not valid"),
        (b"x" * 1_000_001, "too large"),
    ],
)
def test_import_rejects_bad_files(tmp_path: Path, data: bytes, msg: str) -> None:
    with pytest.raises(TemplateError, match=msg):
        store(tmp_path).import_bytes(data)


def test_names_cannot_escape_root(tmp_path: Path) -> None:
    s = store(tmp_path)
    info = s.save(recipe(name="../../evil", folder="../../../tmp"))
    assert info.path.is_relative_to(tmp_path / "templates")
    assert info.path.name == "evil.json"
    with pytest.raises(TemplateError, match="Not a template name"):
        s.load("", "../x")
    with pytest.raises(TemplateError, match="No template"):
        s.load("", "missing")
    assert folder_path(" a / ../b /") == "a/b"
    with pytest.raises(TemplateError, match="levels deep"):
        folder_path("a/b/c/d")


def test_invalid_files_skipped_and_reported(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.save(recipe(id="good", name="Good"))
    bad = tmp_path / "templates" / "bad.json"
    bad.write_text('{"schema_version": 1}')
    (tmp_path / "templates" / ".hidden.json").write_text("{}")
    assert [t.recipe.id for t in s.all()] == ["good"]
    assert list(s.problems()) == [bad]


def test_delete_and_empty_store(tmp_path: Path) -> None:
    s = store(tmp_path)
    assert s.all() == [] and s.find("x") is None
    s.save(recipe(id="a"))
    assert s.delete("a") and not s.delete("a")
