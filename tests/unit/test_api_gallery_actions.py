"""Phase 08 gallery actions: model filter, facets, export, variations, trash, model defaults."""

from __future__ import annotations

import io
import zipfile

import pytest
from tests.studio import generate_recipe, studio_client

from p11.outputs import metadata


@pytest.fixture
def client(tmp_path):  # type: ignore[no-untyped-def]
    with studio_client(tmp_path) as c:
        for i, p in enumerate(["a red mountain", "a blue lake", "a quiet harbour"]):
            job = c.post(
                "/api/jobs",
                headers=c.auth,
                json={"recipe": generate_recipe(p), "template": "scenes" if i else None},
            ).json()
            assert c.wait_job(job["id"])["state"] == "done"
        yield c


def _items(c, **params):  # type: ignore[no-untyped-def]
    return c.get("/api/gallery", headers=c.auth, params=params).json()


def test_model_filter_and_facets(client):
    c = client
    facets = c.get("/api/gallery/facets", headers=c.auth).json()
    assert facets["templates"] == ["scenes"]
    assert facets["models"] == ["realvisxl5-lightning"]
    assert _items(c, model="realvisxl5-lightning")["total"] == 3
    assert _items(c, model="juggernautxl9")["total"] == 0


def test_bulk_export_zip_strips_metadata(client):
    c = client
    ids = [i["id"] for i in _items(c)["items"]]
    r = c.post("/api/gallery/export", headers=c.auth, json={"ids": ids + ids[:1]})
    assert r.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = zf.namelist()
        assert names == [f"p11-{i}.png" for i in ids]  # duplicates dropped, order kept
        assert all(metadata.KEY_RECIPE.encode() not in zf.read(n) for n in names)
    kept = c.post("/api/gallery/export", headers=c.auth,
                  json={"ids": ids[:1], "strip_metadata": False})  # fmt: skip
    with zipfile.ZipFile(io.BytesIO(kept.content)) as zf:
        assert metadata.KEY_RECIPE.encode() in zf.read(zf.namelist()[0])
    assert c.post("/api/gallery/export", headers=c.auth, json={"ids": []}).status_code == 422
    assert c.post("/api/gallery/export", headers=c.auth, json={"ids": [999]}).status_code == 404


def test_seed_variations_follow_the_seed(client):
    c = client
    item = _items(c)["items"][0]
    r = c.post(f"/api/images/{item['id']}/variations", headers=c.auth, json={"count": 3})
    assert r.status_code == 201, r.text
    [job] = r.json()["jobs"]
    done = c.wait_job(job["id"])
    assert done["state"] == "done" and len(done["images"]) == 3
    seeds = [c.get(f"/api/images/{i}/info", headers=c.auth).json() for i in done["images"]]
    assert [s["seed"] for s in seeds] == [item["seed"] + 1, item["seed"] + 2, item["seed"] + 3]
    assert {s["parent_id"] for s in seeds} == {item["id"]}
    assert {s["template"] for s in seeds} == {item["template"]}


def test_prompt_variations_change_words_not_seed(client):
    c = client
    item = _items(c)["items"][0]
    r = c.post(f"/api/images/{item['id']}/variations", headers=c.auth,
               json={"mode": "prompt", "count": 2})  # fmt: skip
    jobs = r.json()["jobs"]
    assert len(jobs) == 2
    for job in jobs:
        [image_id] = c.wait_job(job["id"])["images"]
        info = c.get(f"/api/images/{image_id}/info", headers=c.auth).json()
        assert info["seed"] == item["seed"] and info["parent_id"] == item["id"]
        assert info["prompt"] != item["prompt"]
        assert info["recipe_id"] != item["recipe_id"]
    bad = c.post(f"/api/images/{item['id']}/variations", headers=c.auth, json={"count": 9})
    assert bad.status_code == 422
    assert c.post("/api/images/999/variations", headers=c.auth, json={}).status_code == 404


def test_delete_moves_to_trash_until_emptied(client):
    c = client
    items = _items(c)["items"]
    victim = items[0]
    path = c.studio.paths.outputs / victim["path"]
    child = c.post(f"/api/images/{victim['id']}/variations", headers=c.auth, json={}).json()
    [child_id] = c.wait_job(child["jobs"][0]["id"])["images"]
    r = c.delete(f"/api/images/{victim['id']}", headers=c.auth)
    assert r.status_code == 200, r.text
    assert r.json()["trash"]["count"] == 1
    assert not path.exists() and not metadata.sidecar_path(path).exists()
    trash = c.studio.paths.data / "trash"
    assert sorted(p.suffix for p in trash.iterdir()) == [".json", ".png"]
    assert trash.stat().st_mode & 0o777 == 0o700
    assert c.get(f"/api/images/{victim['id']}/info", headers=c.auth).status_code == 404
    assert c.get(f"/api/images/{child_id}/info", headers=c.auth).json()["parent_id"] is None
    assert _items(c)["total"] == len(items)  # 3 originals - 1 + the variation
    info = c.get("/api/trash", headers=c.auth).json()
    assert info["count"] == 1 and info["bytes"] > 0
    assert c.delete(f"/api/images/{victim['id']}", headers=c.auth).status_code == 404
    assert c.post("/api/trash/empty", headers=c.auth).json() == {"count": 0, "bytes": 0}
    assert not trash.exists()
    assert c.get("/api/trash", headers=c.auth).json() == {"count": 0, "bytes": 0}
    assert c.post("/api/trash/empty", headers=c.auth).status_code == 200


def test_models_carry_registry_defaults(tmp_path):
    with studio_client(tmp_path) as c:
        models = {m["id"]: m for m in c.get("/api/models", headers=c.auth).json()}
        fast = models["realvisxl5-lightning"]
        assert fast["usable"] is True and fast["family"] == "sdxl"
        assert fast["defaults"]["steps"] == 5 and fast["defaults"]["sampler_name"] == "dpmpp_sde"
        assert fast["vae"] == "sdxl-vae-fp16-fix"
        assert models["sdxl-vae-fp16-fix"]["defaults"] is None
