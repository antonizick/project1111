"""Text overlay and logo API routes (Phase 14)."""

from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
from tests.studio import studio_client


def _wait_demo_image(client: TestClient, timeout: float = 20.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for job in client.get("/api/jobs", headers=client.auth).json():  # type: ignore[attr-defined]
            if job["state"] == "done" and job["images"]:
                return int(job["images"][0])
        time.sleep(0.02)
    raise AssertionError("no demo image")


def test_text_fonts_are_listed(tmp_path: Path) -> None:
    with studio_client(tmp_path) as client:
        response = client.get("/api/text/fonts", headers=client.auth)
        assert response.status_code == 200
        fonts = response.json()["fonts"]
        assert {f["id"] for f in fonts} >= {"sans", "display", "serif", "condensed", "mono"}
        assert all(f["licence"] for f in fonts)


def test_text_preview_without_an_image(tmp_path: Path) -> None:
    overlay = {
        "type": "text_overlay",
        "text": "HELLO",
        "font": "display",
        "weight": "bold",
        "size_pct": 20,
        "colour": "#ffffff",
        "colour2": None,
        "align": "center",
        "position": "center",
        "x": None,
        "y": None,
        "margin_pct": 6,
        "letter_spacing": 0.05,
        "stroke_px": 0,
        "stroke_colour": "#000000",
        "shadow": True,
        "also_prompt_model": False,
    }
    with studio_client(tmp_path) as client:
        response = client.post(
            "/api/text/preview",
            json={"overlay": overlay, "width": 640, "height": 480},
            headers=client.auth,
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "image/png"
        with Image.open(io.BytesIO(response.content)) as img:
            assert img.size == (640, 480)


def test_text_preview_rejects_empty_text(tmp_path: Path) -> None:
    with studio_client(tmp_path) as client:
        response = client.post(
            "/api/text/preview",
            json={"overlay": {"type": "text_overlay", "text": ""}},
            headers=client.auth,
        )
        assert response.status_code == 422


def test_logo_export_is_a_zip_of_sizes(tmp_path: Path) -> None:
    with studio_client(tmp_path, seed_demo=True) as client:
        image_id = _wait_demo_image(client)
        response = client.post(
            f"/api/images/{image_id}/logo-export",
            json={"transparent": False, "sizes": [128, 64, 32]},
            headers=client.auth,
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "application/zip"
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = set(archive.namelist())
        assert "favicon.ico" in names
        assert any(name.endswith("-128.png") for name in names)
        assert any(name.endswith("-64.png") for name in names)


def test_logo_export_unknown_image(tmp_path: Path) -> None:
    with studio_client(tmp_path) as client:
        response = client.post(
            "/api/images/999/logo-export", json={"transparent": True}, headers=client.auth
        )
        assert response.status_code == 404


def test_models_page_reads_and_toggles(tmp_path: Path) -> None:
    root = tmp_path / "models"
    root.mkdir()
    with studio_client(tmp_path, models_root=root) as client:
        models = client.get("/api/models", headers=client.auth).json()
        assert models and all(m["state"] == "missing" for m in models)
        assert {"id", "origin", "filename", "size", "licence"} <= set(models[0])
        first = models[0]["id"]
        response = client.post(
            f"/api/models/{first}/enabled", json={"enabled": False}, headers=client.auth
        )
        assert response.status_code == 200
        assert client.get("/api/models", headers=client.auth).json()[0]["enabled"] is False
        plan = client.post(
            "/api/models/plan", json={"target": "default"}, headers=client.auth
        ).json()
        assert plan["target"] == "default" and plan["models"]
        assert "download_bytes" in plan and isinstance(plan["licences_to_accept"], list)
        licences = client.get("/api/models/licences", headers=client.auth).json()["licences"]
        assert licences and all("commercial_use" in row for row in licences)
        assert client.get("/api/models/operations", headers=client.auth).json() == []
