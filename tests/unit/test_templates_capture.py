"""Phase 09: Save as Template (slot inference), starter install and the from-image route."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.helpers import recipe
from tests.studio import generate_recipe, studio_client

from p11.outputs.metadata import RunRecord
from p11.recipe.model import (
    FileRef,
    FixedSeed,
    Generate,
    RandomSeed,
    Slot,
    Upscale,
)
from p11.templates.capture import capture_template
from p11.templates.starter import find_starter_dir, install_starters
from p11.templates.store import TemplateStore


def record(r, **fields):  # type: ignore[no-untyped-def]
    return RunRecord(recipe=r, seed=fields.pop("seed", 4242), **fields)


def test_plain_run_becomes_fixed_or_random_template() -> None:
    rec = record(recipe(Generate(prompt="a lake")))
    fixed = capture_template(rec, name="  Lake  ", tags=("a", "a", " b "))
    assert fixed.name == "Lake" and fixed.tags == ("a", "b")
    assert fixed.seed == FixedSeed(value=4242) and fixed.slots == ()
    assert fixed.id != rec.recipe.id
    assert capture_template(rec, name="Lake", seed="random").seed == RandomSeed()


def test_variable_prompt_becomes_text_slot_with_default() -> None:
    rec = record(recipe(Generate(prompt="a lake at dusk")))
    t = capture_template(rec, name="Lake", variable_prompt=True)
    assert t.steps[0].prompt == "{{prompt}}"  # type: ignore[union-attr]
    assert t.slots == (Slot(name="prompt", kind="text", label="Prompt", required=False,
                            default="a lake at dusk"),)  # fmt: skip


def test_existing_text_slot_keeps_bound_value_as_default_and_images_are_not_copied() -> None:
    r = recipe(
        Generate(prompt="{{scene}}"),
        slots=(Slot(name="scene", kind="text"), Slot(name="face", kind="face_image")),
    )
    rec = record(r, bindings={"scene": "a harbour", "face": FileRef(ref="img-1")})
    t = capture_template(rec, name="T", variable_prompt=True)  # already a slot: left alone
    assert [(s.name, s.default) for s in t.slots] == [("scene", "a harbour"), ("face", None)]
    assert "img-1" not in t.model_dump_json()


def test_source_image_becomes_a_slot_on_the_first_step_that_takes_one() -> None:
    r = recipe(Upscale(), source_image=FileRef(ref="gallery/7"))
    t = capture_template(record(r), name="Up")
    assert t.source_image is None
    assert [(s.name, s.kind) for s in t.slots] == [("source", "image")]
    assert t.steps[0].image_slot == "source"  # type: ignore[union-attr]


def test_source_slot_name_avoids_collisions() -> None:
    r = recipe(Upscale(), slots=(Slot(name="source", kind="text"),),
               source_image=FileRef(ref="gallery/7"))  # fmt: skip
    t = capture_template(record(r), name="Up")
    assert [s.name for s in t.slots] == ["source", "source_2"]


def test_starters_install_once_and_never_come_back(tmp_path: Path) -> None:
    store = TemplateStore(tmp_path / "templates")
    added = install_starters(store)
    assert len(added) == 6 and len(store.all()) == 6
    assert install_starters(store) == []
    store.delete(added[0])
    assert install_starters(store) == []  # deleted by the user: stays deleted
    assert len(store.all()) == 5


def test_starters_are_valid_and_safe() -> None:
    from p11.recipe.presets import ASPECTS, STYLES

    store = TemplateStore(Path("/nonexistent"))
    files = sorted(find_starter_dir().glob("*.json"))
    assert len(files) == 6
    for path in files:
        from p11.recipe.migrate import loads

        r = loads(path.read_bytes())
        step = r.steps[0]
        assert isinstance(step, Generate) and step.style in STYLES and step.aspect in ASPECTS
        assert all(s.kind == "text" or not s.required for s in r.slots)  # one-click runs
        assert r.id.startswith("starter-") and r.folder == "Starter"
    assert store.root == Path("/nonexistent")


def test_bad_starter_is_skipped(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "bad.json").write_text("{not json")
    (src / "future.json").write_text(json.dumps({"schema_version": 99}))
    store = TemplateStore(tmp_path / "t")
    assert install_starters(store, src) == []


@pytest.fixture
def client(tmp_path):  # type: ignore[no-untyped-def]
    with studio_client(tmp_path) as c:
        yield c


def _make_image(c, **recipe_fields):  # type: ignore[no-untyped-def]
    job = c.post("/api/jobs", headers=c.auth,
                 json={"recipe": generate_recipe(**recipe_fields)}).json()  # fmt: skip
    done = c.wait_job(job["id"])
    assert done["state"] == "done"
    return done["images"][0]


def test_from_image_route_saves_runs_and_shows_last_image(client) -> None:  # type: ignore[no-untyped-def]
    c = client
    image_id = _make_image(c, prompt="a red kite over dunes")
    r = c.post("/api/templates/from-image", headers=c.auth, json={
        "image_id": image_id, "name": "Kite", "folder": "Sky", "tags": ["kite"],
        "seed": "random", "variable_prompt": True})  # fmt: skip
    assert r.status_code == 201
    tpl = r.json()
    assert tpl["folder"] == "sky" and tpl["last_image"] is None
    assert [s["name"] for s in tpl["slots"]] == ["prompt"]
    job = c.post("/api/jobs", headers=c.auth, json={
        "recipe": tpl["recipe"], "bindings": {"prompt": "a green kite"},
        "template": tpl["slug"]}).json()  # fmt: skip
    assert c.wait_job(job["id"])["state"] == "done"
    listed = c.get("/api/templates", headers=c.auth).json()
    assert listed[0]["last_image"]["prompt"] == "a green kite"
    assert c.post("/api/templates/from-image", headers=c.auth,
                  json={"image_id": 9999, "name": "x"}).status_code == 404  # fmt: skip


def test_rerun_of_a_fixed_template_reproduces_the_recipe(client) -> None:  # type: ignore[no-untyped-def]
    c = client
    image_id = _make_image(c, prompt="a quiet harbour")
    tpl = c.post("/api/templates/from-image", headers=c.auth,
                 json={"image_id": image_id, "name": "Harbour"}).json()  # fmt: skip
    job = c.post(
        "/api/jobs", headers=c.auth, json={"recipe": tpl["recipe"], "template": tpl["slug"]}
    ).json()
    new = c.wait_job(job["id"])["images"][0]
    a = c.get(f"/api/images/{image_id}/recipe", headers=c.auth).json()
    b = c.get(f"/api/images/{new}/recipe", headers=c.auth).json()
    assert a["seed"] == b["seed"]
    assert a["recipe"]["steps"] == b["recipe"]["steps"]


def test_malformed_and_future_imports_are_refused(client) -> None:  # type: ignore[no-untyped-def]
    c = client
    for body in (b"{not json", json.dumps({"schema_version": 99}).encode(), b'{"id":"x"}'):
        r = c.post("/api/templates/import", headers=c.auth, content=body)
        assert r.status_code in (400, 422), r.text
    assert c.get("/api/templates", headers=c.auth).json() == []
