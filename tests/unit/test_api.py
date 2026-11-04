import json
import time

from fastapi.testclient import TestClient
from tests.helpers import recipe
from tests.studio import studio_client

from p11 import __version__
from p11.api.app import NO_TELEMETRY, create_app
from p11.engine.fake import FakeConfig, FakeEngine
from p11.recipe.model import Generate

BASE = "http://127.0.0.1:8111"


def _submit(client, body):  # type: ignore[no-untyped-def]
    r = client.post("/api/jobs", headers=client.auth, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_healthz():
    r = TestClient(create_app(fake=True), base_url=BASE).get("/healthz")
    assert r.status_code == 200
    assert r.json() == {
        "status": "ok",
        "version": __version__,
        "busy": "idle",
        "queue": {"running": 0, "waiting": 0},
    }


def test_healthz_busy_while_a_job_runs_and_while_jobs_wait(tmp_path):
    """The token-free endpoint tells OCC whether work is running, never what the work is."""
    body = recipe(Generate(prompt="a quiet harbour", aspect="1:1-1024")).model_dump(mode="json")
    slow = FakeEngine(FakeConfig(step_delay=0.25, node_delay=0.05))
    with studio_client(tmp_path, engine=slow) as c:
        first = _submit(c, {"recipe": body})
        second = _submit(c, {"recipe": body})
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            health = c.get("/healthz").json()
            if health["queue"]["running"] == 1 and health["queue"]["waiting"] == 1:
                break
            time.sleep(0.02)
        else:  # pragma: no cover - timing guard
            raise AssertionError(f"queue never showed one running and one waiting: {health}")

        assert health["busy"] == "busy"
        assert set(health) == {"status", "version", "busy", "queue"}
        assert set(health["queue"]) == {"running", "waiting"}
        text = json.dumps(health)
        for leaked in (first["id"], second["id"], "quiet harbour", "recipe"):
            assert leaked not in text

        c.wait_job(first["id"])
        c.wait_job(second["id"])
        assert c.get("/healthz").json()["busy"] == "idle"


def test_serves_static(tmp_path):
    (tmp_path / "index.html").write_text("<h1>hi</h1>")
    c = TestClient(create_app(web_dir=tmp_path, fake=True), base_url=BASE)
    assert "hi" in c.get("/").text
    assert c.get("/healthz").status_code == 200


def test_fastapi_telemetry_is_off():
    app = create_app(fake=True)
    assert all(v is False for v in NO_TELEMETRY.values())
    assert not app._native_telemetry.enabled()


def test_default_engine_is_the_pinned_comfyui_and_not_started():
    from p11.engine.comfy import ComfyEngine

    app = create_app(sampler=None)
    assert isinstance(app.state.engine, ComfyEngine)
    assert app.state.studio.fake is False
