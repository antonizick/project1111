import io
import json
import re
import stat
import struct
import zlib
from datetime import datetime
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from PIL import Image, PngImagePlugin
from tests.helpers import recipe

from p11.outputs import metadata as md
from p11.outputs.index import GalleryIndex, ImageEntry, fts_query, prompt_text
from p11.outputs.layout import output_path, slugify, template_dir_name
from p11.recipe.model import FileRef, Generate, Slot

NOW = datetime(2026, 11, 2, 18, 45, 7)


def mode(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


# ---------------------------------------------------------------------------------------------
# Layout


def test_output_path_layout_and_permissions(tmp_path: Path) -> None:
    root = tmp_path / "Pictures" / "P11"
    p = output_path(root, NOW, "Software Logo Dark", 1111)
    assert p == root / "2026-11-02" / "software-logo-dark" / "184507-1111.png"
    assert p.exists() and p.stat().st_size == 0 and mode(p) == 0o600
    for d in (root, root / "2026-11-02", p.parent):
        assert mode(d) == 0o700
    adhoc = output_path(root, NOW, None, 5, step=2)
    assert adhoc.relative_to(root).as_posix() == "2026-11-02/adhoc/184507-5-2.png"
    assert output_path(root, NOW, None, 5, step="Upscale x2").name == "184507-5-upscale-x2.png"


def test_output_path_collisions(tmp_path: Path) -> None:
    names = [output_path(tmp_path, NOW, None, 9).name for _ in range(3)]
    assert names == ["184507-9.png", "184507-9-2.png", "184507-9-3.png"]


def test_output_path_rejects_negative_seed(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        output_path(tmp_path, NOW, None, -1)


def test_existing_root_permissions_tightened(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir(mode=0o755)
    output_path(root, NOW, None, 1)
    assert mode(root) == 0o700


@pytest.mark.parametrize(
    ("text", "slug"),
    [
        ("Software Logo Dark", "software-logo-dark"),
        ("  ../../etc/passwd ", "etc-passwd"),
        ("Café Crème", "cafe-creme"),
        ("☕☕", "untitled"),
        ("", "untitled"),
        ("a" * 100, "a" * 64),
    ],
)
def test_slugify(text: str, slug: str) -> None:
    assert slugify(text) == slug


def test_template_named_adhoc_gets_own_folder() -> None:
    assert template_dir_name("Adhoc") == "adhoc-template"
    assert template_dir_name(None) == "adhoc"


@settings(max_examples=300)
@given(st.text(max_size=200))
def test_slug_is_always_safe(text: str) -> None:
    s = slugify(text)
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", s)
    assert len(s) <= 64
    assert s not in (".", "..")


# ---------------------------------------------------------------------------------------------
# Metadata


def png_bytes(**text: str) -> bytes:
    info = PngImagePlugin.PngInfo()
    for k, v in text.items():
        info.add_text(k, v)
    buf = io.BytesIO()
    Image.new("RGB", (8, 4), (200, 30, 30)).save(buf, "PNG", pnginfo=info)
    return buf.getvalue()


def record(**kw: object) -> md.RunRecord:
    r = recipe(
        Generate(prompt="a {{thing}} at dawn ☀"),
        slots=(
            Slot(name="thing", kind="text"),
            Slot(name="face", kind="face_image", required=False),
        ),
    )
    base: dict[str, object] = {
        "recipe": r,
        "bindings": {"thing": "lighthouse", "face": FileRef(ref="uploads/abc.png")},
        "seed": 1111,
        "model_hashes": {"realvisxl5-lightning": "f" * 64},
        "engine_version": "comfyui v0.43.0 (426f5ee)",
        "timings": {"total_s": 18.3},
        "created_at": datetime(2026, 11, 2, 18, 45, 7).astimezone(),
    }
    base.update(kw)
    return md.RunRecord.model_validate(base)


def test_sidecar_round_trip(tmp_path: Path) -> None:
    img = tmp_path / "a.png"
    img.write_bytes(png_bytes())
    rec = record()
    side = md.write_sidecar(img, rec)
    assert side == tmp_path / "a.json" and mode(side) == 0o600
    assert md.read_sidecar(side) == rec
    assert isinstance(md.read_sidecar(side).bindings["face"], FileRef)


def test_sidecar_holds_refs_not_contents(tmp_path: Path) -> None:
    img = tmp_path / "a.png"
    img.write_bytes(png_bytes())
    text = md.write_sidecar(img, record()).read_text()
    assert "uploads/abc.png" in text and "base64" not in text


def test_png_embed_round_trip_keeps_pixels(tmp_path: Path) -> None:
    img = tmp_path / "a.png"
    original = png_bytes(prompt='{"comfy": 1}')
    img.write_bytes(original)
    rec = record()
    md.embed_record(img, rec)
    assert md.read_recipe_from_png(img) == rec.recipe
    assert md.read_run_from_png(img) == rec
    with Image.open(img) as im:
        assert im.tobytes() == Image.open(io.BytesIO(original)).tobytes()
        assert json.loads(im.text["p11:recipe"])["id"] == "r-test"  # Pillow can read it too
    md.embed_record(img, rec)  # re-embedding replaces, not duplicates
    assert img.read_bytes().count(b"p11:recipe") == 1


def test_strip_metadata(tmp_path: Path) -> None:
    img = tmp_path / "a.png"
    img.write_bytes(png_bytes(prompt="secret prompt", workflow="{}"))
    md.embed_record(img, record())
    data = img.read_bytes()
    exif = struct.pack(">I", 4) + b"eXIf" + b"abcd" + struct.pack(">I", zlib.crc32(b"eXIfabcd"))
    iend = data.rindex(b"IEND") - 4
    img.write_bytes(data[:iend] + exif + data[iend:])
    clean = md.strip_metadata(img)
    assert md.text_chunks(clean) == {}
    for needle in (b"secret", b"p11:", b"eXIf", b"workflow"):
        assert needle not in clean
    with Image.open(io.BytesIO(clean)) as im:
        assert im.size == (8, 4)


def test_png_without_recipe_and_bad_pngs(tmp_path: Path) -> None:
    img = tmp_path / "a.png"
    img.write_bytes(png_bytes())
    with pytest.raises(md.MetadataError, match="no P11 recipe"):
        md.read_recipe_from_png(img)
    with pytest.raises(md.MetadataError, match="no P11 run"):
        md.read_run_from_png(img)
    with pytest.raises(md.MetadataError, match="not a PNG"):
        md.text_chunks(b"GIF89a")
    good = png_bytes()
    with pytest.raises(md.MetadataError, match="truncated"):
        md.text_chunks(good[:-6])
    with pytest.raises(md.MetadataError, match="no IEND"):
        md.text_chunks(good[: good.rindex(b"IEND") - 4])
    corrupt = bytearray(good)
    corrupt[20] ^= 0xFF
    with pytest.raises(md.MetadataError, match="CRC"):
        md.text_chunks(bytes(corrupt))
    with pytest.raises(md.MetadataError, match="truncated PNG chunk header"):
        md.text_chunks(md.PNG_SIGNATURE + b"\x00\x00")


def test_text_chunk_kinds() -> None:
    info = PngImagePlugin.PngInfo()
    info.add_text("plain", "a")
    info.add_text("zipped", "b" * 2000, zip=True)
    info.add_itxt("intl", "ünï", zip=False)
    buf = io.BytesIO()
    Image.new("L", (2, 2)).save(buf, "PNG", pnginfo=info)
    assert md.text_chunks(buf.getvalue()) == {"plain": "a", "zipped": "b" * 2000, "intl": "ünï"}


def test_newer_record_version_refused() -> None:
    data = json.loads(record().to_json())
    data["record_version"] = 99
    with pytest.raises(md.MetadataError, match="newer P11"):
        md.RunRecord.from_json(json.dumps(data))
    with pytest.raises(md.MetadataError):
        md.RunRecord.from_json("[]")


# ---------------------------------------------------------------------------------------------
# Gallery index


def entry(path: str, prompt: str = "", **kw: object) -> ImageEntry:
    return ImageEntry(path=path, created_at=kw.pop("created_at", "2026-11-02T18:00:00"),  # type: ignore[arg-type]
                      recipe_id="r", seed=1, prompt=prompt, **kw)  # type: ignore[arg-type]  # fmt: skip


def test_index_migrates_and_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "idx" / "gallery.db"
    with GalleryIndex(db) as idx:
        assert idx.version == 1
    with GalleryIndex(db) as idx:
        assert idx.version == 1 and idx.count() == 0


def test_index_refuses_newer_db(tmp_path: Path) -> None:
    db = tmp_path / "g.db"
    GalleryIndex(db).close()
    import sqlite3

    con = sqlite3.connect(db)
    con.execute("PRAGMA user_version = 7")
    con.commit()
    con.close()
    with pytest.raises(RuntimeError, match="newer P11"):
        GalleryIndex(db)


def test_index_crud_search_and_parents() -> None:
    with GalleryIndex(":memory:") as idx:
        a = idx.add(
            entry("d/a.png", "misty mountain lake at sunrise", created_at="2026-11-02T10:00")
        )
        b = idx.add(
            entry("d/b.png", "neon city street", template="city", created_at="2026-11-02T11:00")
        )
        c = idx.add(entry("d/c.png", "mountain cabin", parent_id=a, created_at="2026-11-02T12:00"))
        assert [e.path for e in idx.search("mount")] == ["d/c.png", "d/a.png"]
        assert [e.path for e in idx.search("MOUNTAIN lake")] == ["d/a.png"]
        assert [e.path for e in idx.search('neon" * (')] == ["d/b.png"]  # FTS syntax is inert
        assert [e.path for e in idx.search(template="city")] == ["d/b.png"]
        assert len(idx.search()) == 3
        assert [e.id for e in idx.children(a)] == [c]
        idx.set_favourite(b)
        assert [e.path for e in idx.search(favourites=True)] == ["d/b.png"]
        # Upsert by path keeps the row and updates FTS.
        assert idx.add(entry("d/b.png", "forest trail", template="city")) == b
        assert idx.search("neon") == [] and idx.search("forest")[0].id == b
        assert idx.get(b) is not None and idx.get(b).favourite  # type: ignore[union-attr]
        assert idx.by_path("d/a.png").id == a  # type: ignore[union-attr]
        idx.delete(a)
        assert idx.get(a) is None and idx.get(c).parent_id is None  # type: ignore[union-attr]
        assert idx.search("misty") == []
        assert idx.by_path("nope") is None
        assert len(idx.search(limit=1)) == 1 and len(idx.search(offset=5)) == 0


def test_fts_query() -> None:
    assert fts_query('neon" OR city*') == '"neon"* "or"* "city"*'
    assert fts_query("  ") == ""


def test_prompt_text_fills_slots() -> None:
    rec = record()
    assert prompt_text(rec.recipe, rec.bindings) == "a lighthouse at dawn ☀"
    assert prompt_text(rec.recipe, {"bogus": "x"}) == "a  at dawn ☀"


def test_reindex_from_sidecars(tmp_path: Path) -> None:
    root = tmp_path / "out"
    first = output_path(root, NOW, None, 1111)
    first.write_bytes(png_bytes())
    rel1 = first.relative_to(root).as_posix()
    out0 = {"step_index": 0, "step_type": "generate", "path": rel1, "width": 8, "height": 4}
    md.write_sidecar(first, record(step_outputs=[out0]))
    second = output_path(root, NOW, "Wallpapers", 1112)
    second.write_bytes(png_bytes())
    md.write_sidecar(second, record(seed=1112, parent=rel1, template="wallpapers"))
    orphan = output_path(root, NOW, None, 3)  # sidecar without image → skipped
    md.write_sidecar(orphan, record())
    orphan.unlink()
    (root / "junk.json").write_text("{not json")
    (root / "other.json").write_text(json.dumps({"hello": 1}))

    with GalleryIndex(tmp_path / "g.db") as idx:
        idx.add(entry("stale.png", "old"))
        assert idx.reindex(root) == 2
        assert idx.count() == 2 and idx.by_path("stale.png") is None
        e1 = idx.by_path(rel1)
        assert e1 is not None and (e1.width, e1.height, e1.seed) == (8, 4, 1111)
        assert e1.model == "realvisxl5-lightning" and e1.template is None
        e2 = idx.by_path(second.relative_to(root).as_posix())
        assert e2 is not None and e2.parent_id == e1.id and e2.template == "wallpapers"
        assert [e.id for e in idx.search("lighthouse")] == [e2.id, e1.id] or len(
            idx.search("lighthouse")
        ) == 2
        idx.set_favourite(e1.id)  # type: ignore[arg-type]
        assert idx.reindex(root) == 2
        assert idx.by_path(rel1).favourite  # type: ignore[union-attr]
    with GalleryIndex(tmp_path / "g2.db") as idx:
        assert idx.reindex(tmp_path / "missing") == 0
