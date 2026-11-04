"""Phase 16 hardening regressions: middleware edge cases found in the security review (S2)."""

from __future__ import annotations

import pytest
from tests.studio import studio_client

from p11.api.security import MAX_LAUNCH_CODES, Session


@pytest.fixture
def client(tmp_path):  # type: ignore[no-untyped-def]
    with studio_client(tmp_path) as c:
        yield c


def test_a_non_ascii_token_is_a_401_not_a_crash(client):
    # Headers decode as latin-1; hmac.compare_digest raised TypeError on non-ASCII str (a 500).
    for header in ("x-p11-token", "authorization"):
        value = b"\xe9\xe9" if header == "x-p11-token" else b"Bearer \xe9\xe9"
        r = client.get("/api/system", headers={header: value})
        assert r.status_code == 401, (header, r.status_code)
    assert not Session().check("é" * 43)


def test_a_non_ascii_launch_code_is_refused(client):
    client.session.mint_launch_code()
    assert not client.session.redeem("é" * 32)


@pytest.mark.parametrize(
    "path",
    ["/api//system", "/api/system/", "/%61pi/system", "/static/../api/system", "/./api/system"],
)
def test_path_spellings_still_need_the_token(client, path):
    r = client.get(path)
    assert r.status_code in (401, 404), (path, r.status_code)
    assert r.status_code != 200


@pytest.mark.parametrize(
    ("headers", "method"),
    [
        ({"origin": "null"}, "post"),  # sandboxed iframe / file:// page
        ({"origin": "http://127.0.0.1:9999"}, "get"),  # another local server: same-site, not ours
        ({"sec-fetch-site": "same-site"}, "get"),
        ({"sec-fetch-site": "cross-site"}, "get"),
    ],
)
def test_other_local_origins_are_refused(client, headers, method):
    call = client.post if method == "post" else client.get
    kwargs = {"json": {}} if method == "post" else {}
    r = call("/api/jobs" if method == "post" else "/api/system",
             headers={**client.auth, **headers}, **kwargs)  # fmt: skip
    assert r.status_code == 403


def test_outstanding_launch_codes_are_capped():
    s = Session()
    codes = [s.mint_launch_code(now=float(i)) for i in range(MAX_LAUNCH_CODES * 3)]
    assert len(s._codes) <= MAX_LAUNCH_CODES
    assert s.redeem(codes[-1], now=float(len(codes)))  # the newest still works
    assert not s.redeem(codes[0], now=float(len(codes)))  # the oldest were dropped


def test_doctor_names_the_optional_sets_without_failing():
    from types import SimpleNamespace as NS

    from p11.doctor import optional_sets

    class Manager:
        def statuses(self, include_unregistered=False):
            return [
                NS(sets=("face",), state="missing"),
                NS(sets=("face",), state="missing"),
                NS(sets=("control",), state="installed"),
                NS(sets=("control",), state="missing"),
                NS(sets=("default",), state="installed"),
            ]

    line = optional_sets(Manager())
    assert "face: not installed" in line and "p11 models install face" in line
    assert "control: 1 of 2 missing" in line
