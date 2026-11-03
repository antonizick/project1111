"""Gallery, images, templates, presets, models and system routes."""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image
from tests.helpers import recipe
from tests.studio import generate_recipe, studio_client

from p11.outputs import metadata
from p11.recipe.model import Generate


@pytest.fixture
def client(tmp_path):  # type: ignore[no-untyped-def]
    with studio_client(tmp_path) as c:
        prompts = ["a red mountain", "a blue lake", "a red barn", "mountain lake at dawn"]
        for i, p in enumerate(prompts):
            job = c.post(
                "/api/jobs",
                headers=c.auth,
                json={"recipe": generate_recipe(p), "template": "scenes" if i % 2 else None},
            ).json()
            c.wait_job(job["id"])
        yield c


def test_gallery_paging_search_and_filters(client):
    c = client
    page = c.get("/api/gallery?limit=3", headers=c.auth).json()
    assert page["total"] == 4 and len(page["items"]) == 3 and page["limit"] == 3
    rest = c.get("/api/gallery?limit=3&offset=3", headers=c.auth).json()
    assert len(rest["items"]) == 1
    ids = [i["id"] for i in page["items"] + rest["items"]]
    assert ids == sorted(ids, reverse=True)  # newest first
    red = c.get("/api/gallery?q=red", headers=c.auth).json()
    assert red["total"] == 2
    assert c.get("/api/gallery?q=mount", headers=c.auth).json()["total"] == 2  # prefix match
    assert c.get("/api/gallery?template=scenes", headers=c.auth).json()["total"] == 2
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert c.get("/api/gallery", params={"since": future}, headers=c.auth).json()["total"] == 0
    assert c.get("/api/gallery", params={"until": future}, headers=c.auth).json()["total"] == 4
    assert c.get('/api/gallery?q="OR*', headers=c.auth).status_code == 200  # FTS syntax ignored


def test_favourites(client):
    c = client
    first = c.get("/api/gallery", headers=c.auth).json()["items"][0]["id"]
    r = c.post(f"/api/images/{first}/favourite", headers=c.auth, json={"favourite": True})
    assert r.json()["favourite"] is True
    assert c.get("/api/gallery?favourites=true", headers=c.auth).json()["total"] == 1
    c.post(f"/api/images/{first}/favourite", headers=c.auth, json={"favourite": False})
    assert c.get("/api/gallery?favourites=true", headers=c.auth).json()["total"] == 0
    assert c.post("/api/images/999/favourite", headers=c.auth, json={}).status_code == 404


def test_image_thumb_export_and_recipe(client, tmp_path):
    c = client
    item = c.get("/api/gallery", headers=c.auth).json()["items"][0]
    full = c.get(item["url"], headers=c.auth)
    assert full.headers["content-type"] == "image/png"
    assert metadata.KEY_RECIPE.encode() in full.content
    thumb = c.get(item["thumb"] + "?size=300", headers=c.auth)
    assert thumb.headers["content-type"] == "image/webp"
    with Image.open(io.BytesIO(thumb.content)) as img:
        assert max(img.size) == 256
    assert c.get(item["thumb"], headers=c.auth).content  # cached
    stripped = c.post(f"/api/images/{item['id']}/export", headers=c.auth, json={})
    assert "attachment" in stripped.headers["content-disposition"]
    assert metadata.KEY_RECIPE.encode() not in stripped.content
    kept = c.post(f"/api/images/{item['id']}/export", headers=c.auth,
                  json={"strip_metadata": False})  # fmt: skip
    assert kept.content == full.content
    rec = c.get(f"/api/images/{item['id']}/recipe", headers=c.auth).json()
    assert rec["recipe"]["steps"][0]["prompt"] == "mountain lake at dawn"
    # without the sidecar, the recipe comes from the PNG chunks
    path = c.studio.paths.outputs / item["path"]
    metadata.sidecar_path(path).unlink()
    assert c.get(f"/api/images/{item['id']}/recipe", headers=c.auth).json()["seed"] == rec["seed"]
    path.unlink()
    assert c.get(item["url"], headers=c.auth).status_code == 404
    assert c.get("/api/images/12345", headers=c.auth).status_code == 404
    assert c.get("/api/images/12345/thumb", headers=c.auth).status_code == 404


def test_image_paths_cannot_escape_the_outputs_root(client, tmp_path):
    from p11.outputs.index import GalleryIndex, ImageEntry

    secret = tmp_path / "secret.png"
    secret.write_bytes(b"\x89PNG")
    c = client
    with GalleryIndex(tmp_path / "data" / "gallery.db") as other:  # its own connection
        evil = other.add(ImageEntry(path="../secret.png", created_at="2026", recipe_id="x", seed=1))
    assert c.get(f"/api/images/{evil}", headers=c.auth).status_code == 404


def test_templates_crud_import_export(tmp_path):
    with studio_client(tmp_path) as c:
        tpl = recipe(Generate(prompt="{{name}} logo"), name="Logo maker", tags=("logo",),
                     folder="Logos", slots=({"name": "name", "kind": "text"},))  # fmt: skip
        body = tpl.model_dump(mode="json")
        r = c.post("/api/templates", headers=c.auth, json=body)
        assert r.status_code == 201, r.text
        made = r.json()
        assert made["folder"] == "logos" and made["slug"] == "logo-maker" and made["slots"]
        assert c.post("/api/templates", headers=c.auth, json=body).status_code == 409
        assert [t["id"] for t in c.get("/api/templates?q=logo", headers=c.auth).json()] == [tpl.id]
        assert c.get("/api/templates?tag=nope", headers=c.auth).json() == []
        assert c.get("/api/templates/folders", headers=c.auth).json() == ["logos"]
        body["name"] = "Logo maker v2"
        up = c.put(f"/api/templates/{tpl.id}", headers=c.auth, json=body)
        assert up.json()["name"] == "Logo maker v2"
        assert c.put("/api/templates/other", headers=c.auth, json=body).status_code == 422
        exported = c.get(f"/api/templates/{tpl.id}/export", headers=c.auth)
        assert "attachment" in exported.headers["content-disposition"]
        imported = c.post("/api/templates/import", headers=c.auth, content=exported.content)
        assert imported.status_code == 201 and imported.json()["id"] != tpl.id
        bad = c.post("/api/templates/import", headers=c.auth, content=b"{not json")
        assert bad.status_code == 422
        assert c.get(f"/api/templates/{tpl.id}", headers=c.auth).json()["name"] == "Logo maker v2"
        assert c.delete(f"/api/templates/{tpl.id}", headers=c.auth).status_code == 204
        assert c.delete(f"/api/templates/{tpl.id}", headers=c.auth).status_code == 404
        assert c.get(f"/api/templates/{tpl.id}", headers=c.auth).status_code == 404
        assert (tmp_path / "templates").stat().st_mode & 0o777 == 0o700


def test_presets_models_and_system(tmp_path):
    with studio_client(tmp_path) as c:
        presets = c.get("/api/presets", headers=c.auth).json()
        assert "16:9-1920x1080" in {a["id"] for a in presets["aspects"]}
        assert "photoreal" in {s["id"] for s in presets["styles"]}
        models = c.get("/api/models", headers=c.auth).json()
        assert {m["id"] for m in models} >= {"realvisxl5-lightning", "sdxl-vae-fp16-fix"}
        assert all(m["state"] == "missing" for m in models)  # empty temp models root
        system = c.get("/api/system", headers=c.auth).json()
        assert system["fake"] is True and system["engine"]["state"] == "stopped"
        assert system["queue"] == {"current": None, "waiting": 0}
        assert set(system["disk"]) == {"outputs", "models", "data"} and system["gpu"] is None


def test_demo_gallery_in_fake_mode(tmp_path):
    with studio_client(tmp_path, seed_demo=True) as c:
        jobs = c.get("/api/jobs", headers=c.auth).json()
        assert len(jobs) == 6
        for j in jobs:
            c.wait_job(j["id"])
        page = c.get("/api/gallery?template=demo", headers=c.auth).json()
        assert page["total"] == 6
    with studio_client(tmp_path, seed_demo=True) as c:  # not seeded twice
        assert len(c.get("/api/jobs", headers=c.auth).json()) == 6
