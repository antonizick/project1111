from fastapi.testclient import TestClient

from p11 import __version__
from p11.api.app import create_app


def test_healthz():
    r = TestClient(create_app()).get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": __version__}


def test_serves_static(tmp_path):
    (tmp_path / "index.html").write_text("<h1>hi</h1>")
    c = TestClient(create_app(web_dir=tmp_path))
    assert "hi" in c.get("/").text
    assert c.get("/healthz").status_code == 200
