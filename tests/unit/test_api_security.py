"""Middleware (S1, S2): Host, Origin, token, cookie, CSP and size caps."""

from __future__ import annotations

import json

import pytest
from tests.studio import BASE, studio_client

from p11 import logs, webbundle
from p11.api import security
from p11.api.security import CSP, Session, body_cap, request_token


@pytest.fixture
def client(tmp_path):  # type: ignore[no-untyped-def]
    with studio_client(tmp_path) as c:
        yield c


def test_healthz_needs_no_token_but_a_good_host(client):
    assert client.get("/healthz").status_code == 200
    r = client.get("/healthz", headers={"host": "evil.example:8111"})
    assert r.status_code == 421
    assert r.json()["code"] == "security.host"


@pytest.mark.parametrize("host", ["evil.example", "127.0.0.1:9999", "localhost", "0.0.0.0:8111"])
def test_bad_host_is_refused_everywhere(client, host):
    r = client.get("/api/system", headers={**client.auth, "host": host})
    assert r.status_code == 421


def test_localhost_name_is_allowed(client):
    r = client.get("/api/system", headers={**client.auth, "host": "localhost:8111"})
    assert r.status_code == 200


def test_missing_or_wrong_token_is_refused(client):
    assert client.get("/api/system").status_code == 401
    r = client.get("/api/system", headers={"authorization": "Bearer nope"})
    assert r.status_code == 401
    assert r.json()["code"] == "security.token"
    assert "p11 open" in r.json()["hint"]
    assert (
        client.get("/api/system", headers={"x-p11-token": client.session.token}).status_code == 200
    )


def test_openapi_is_behind_the_token(client):
    assert client.get("/api/openapi.json").status_code == 401
    assert client.get("/api/openapi.json", headers=client.auth).json()["info"]["title"]
    assert client.get("/docs").status_code == 404


def test_foreign_origin_is_refused_for_state_changes(client):
    r = client.post("/api/jobs", headers={**client.auth, "origin": "http://evil.example"}, json={})
    assert r.status_code == 403
    assert r.json()["code"] == "security.origin"
    ok = client.post("/api/jobs", headers={**client.auth, "origin": BASE}, json={})
    assert ok.status_code == 422  # passed the middleware, failed validation


def test_cross_site_fetch_metadata_is_refused_for_api_reads(client):
    r = client.get("/api/gallery", headers={**client.auth, "sec-fetch-site": "cross-site"})
    assert r.status_code == 403
    same = client.get("/api/gallery", headers={**client.auth, "sec-fetch-site": "same-origin"})
    assert same.status_code == 200


def test_cookie_works_for_reads_only(client):
    cookie = {"cookie": f"p11_session={client.session.token}"}
    assert client.get("/api/gallery", headers=cookie).status_code == 200
    r = client.post("/api/images/1/favourite", headers=cookie, json={"favourite": True})
    assert r.status_code == 401  # a forged POST carrying only the cookie never works


def test_security_headers_on_every_response(client, tmp_path):
    for r in (client.get("/healthz"), client.get("/api/system"), client.get("/api/system",
              headers=client.auth)):  # fmt: skip
        assert r.headers["content-security-policy"] == CSP
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["referrer-policy"] == "no-referrer"
        assert r.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in CSP and "http" not in CSP  # no remote origins
    assert client.get("/api/system", headers=client.auth).headers["cache-control"] == "no-store"
    assert "access-control-allow-origin" not in client.get("/api/system").headers


def test_static_files_get_the_csp(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<h1>hi</h1>")
    with studio_client(tmp_path, web_dir=web) as c:
        r = c.get("/")
        assert r.status_code == 200 and "hi" in r.text
        assert r.headers["content-security-policy"] == CSP


def test_index_is_revalidated_and_hashed_assets_stay_cacheable(tmp_path):
    """A rebuilt bundle must reach an open app window (ADR-0043)."""
    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<h1>hi</h1>")
    (web / "assets" / "index-abc123.js").write_text("1")
    with studio_client(tmp_path, web_dir=web) as c:
        for path in ("/", "/index.html"):
            first = c.get(path)
            assert first.headers["cache-control"] == "no-cache", path
            again = c.get(path, headers={"if-none-match": first.headers["etag"]})
            assert again.status_code == 304 and again.headers["cache-control"] == "no-cache"
        assert "cache-control" not in c.get("/assets/index-abc123.js").headers
        assert c.get("/api/system", headers=c.auth).headers["cache-control"] == "no-store"


def test_healthz_and_system_name_the_build_and_nothing_else_about_it(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<h1>hi</h1>")
    (web / webbundle.STAMP).write_text(
        json.dumps({"source_hash": "abcdef0123456789", "built_at": "x", "version": "1"})
    )
    with studio_client(tmp_path, web_dir=web) as c:
        assert c.get("/healthz").json()["web"] == "abcdef01"
        assert c.get("/api/system", headers=c.auth).json()["web"] == "abcdef01"


def test_launch_code_is_one_time_and_expires(client):
    code = client.post("/api/session/launch", headers=client.auth).json()["code"]
    r = client.post("/api/session", json={"code": code})
    assert r.status_code == 200
    assert r.json()["token"] == client.session.token
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    again = client.post("/api/session", json={"code": code})
    assert again.status_code == 401 and "already used" in again.json()["message"]
    s = Session()
    old = s.mint_launch_code(now=0.0)
    assert not s.redeem(old, now=security.LAUNCH_TTL + 1)
    assert not s.redeem("never-issued-code", now=0.0)


def test_session_needs_a_code_not_the_token(client):
    assert client.post("/api/session", json={"code": client.session.token}).status_code == 401
    assert client.post("/api/session/launch").status_code == 401


def test_oversized_bodies_are_refused(client):
    big = b"x" * (security.DEFAULT_BODY_CAP + 1)
    r = client.post("/api/jobs", headers={**client.auth, "content-type": "application/json"},
                    content=big)  # fmt: skip
    assert r.status_code == 413
    assert r.json()["code"] == "request.too-large"

    def chunks():  # no Content-Length: the streamed count must catch it
        for _ in range(3):
            yield b"x" * security.DEFAULT_BODY_CAP

    r = client.post("/api/templates", headers={**client.auth, "content-type": "application/json"},
                    content=chunks())  # fmt: skip
    assert r.status_code == 413
    bad = client.post("/api/jobs", headers={**client.auth, "content-length": "abc"}, content=b"")
    assert bad.status_code in (400, 413)


def test_body_caps_per_path():
    assert body_cap("/api/uploads") == security.BODY_CAPS["/api/uploads"]
    assert body_cap("/api/uploadsX") == security.DEFAULT_BODY_CAP
    assert body_cap("/api/templates/import") == security.MIB


def test_request_token_sources():
    assert request_token({"authorization": "Bearer abc"}, "POST") == "abc"
    assert request_token({"x-p11-token": "abc"}, "POST") == "abc"
    assert request_token({"cookie": "a=1; p11_session=abc"}, "GET") == "abc"
    assert request_token({"cookie": "p11_session=abc"}, "POST") is None
    assert request_token({}, "GET") is None


def test_websockets_are_refused(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/api/events") as ws:
        ws.receive_text()


def test_token_file_is_private_and_redacted(tmp_path):
    s = Session()
    path = s.write(tmp_path / "run" / "studio.token")
    assert path.stat().st_mode & 0o777 == 0o600
    assert security.read_token(path) == s.token
    assert logs.redact(f"token={s.token}") == "token=[redacted]"
    assert security.read_token(tmp_path / "missing") is None
