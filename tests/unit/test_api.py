from fastapi.testclient import TestClient

from p11 import __version__
from p11.api.app import NO_TELEMETRY, create_app

BASE = "http://127.0.0.1:8111"


def test_healthz():
    r = TestClient(create_app(fake=True), base_url=BASE).get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": __version__}


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
