"""The text_overlay step through a whole job on the FakeEngine (Phase 14)."""

from __future__ import annotations

from pathlib import Path

from tests.studio import generate_recipe, studio_client

from p11.recipe.model import Generate, TextOverlay


def test_text_overlay_is_saved_after_the_generate_step(tmp_path: Path) -> None:
    steps = (
        Generate(prompt="a paper plane", style="logo-flat", aspect="logo-1:1"),
        TextOverlay(text="PRODUCT NAME", font="display", weight="bold", size_pct=14),
    )
    with studio_client(tmp_path) as client:
        response = client.post(
            "/api/jobs", json={"recipe": generate_recipe(steps=steps)}, headers=client.auth
        )
        assert response.status_code == 201, response.text
        job = client.wait_job(response.json()["id"])
        assert job["state"] == "done", job
        assert len(job["images"]) == 2
        text_image = client.get(f"/api/images/{job['images'][-1]}/info", headers=client.auth)
        assert text_image.status_code == 200
        assert text_image.json()["width"] == 1024
        record = client.get(f"/api/images/{job['images'][-1]}/recipe", headers=client.auth).json()
        assert record["recipe"]["steps"][-1]["type"] == "text_overlay"


def test_let_the_model_try_text_leaves_the_image_alone(tmp_path: Path) -> None:
    steps = (
        Generate(prompt="a paper plane", style="logo-flat", aspect="logo-1:1"),
        TextOverlay(text="PRODUCT NAME", also_prompt_model=True),
    )
    with studio_client(tmp_path) as client:
        response = client.post(
            "/api/jobs", json={"recipe": generate_recipe(steps=steps)}, headers=client.auth
        )
        assert response.status_code == 201, response.text
        job = client.wait_job(response.json()["id"])
        assert job["state"] == "done", job
        assert len(job["images"]) == 1
