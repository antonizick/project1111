import errno
import hashlib
import os

import pytest
from tests.fixtures.model_server import serve

from p11.models import download as dl
from p11.models.download import (
    DiskSpaceError,
    Downloader,
    DownloadError,
    DownloadItem,
    HashMismatchError,
    SecretsError,
    human_size,
    load_tokens,
)

BODY = os.urandom(3 * dl.CHUNK + 1234)
SHA = hashlib.sha256(BODY).hexdigest()
SIZE = len(BODY)


@pytest.fixture
def server():
    yield from serve()


def make(**kw):
    kw.setdefault("insecure_hosts", ["127.0.0.1", "localhost"])
    kw.setdefault("sleep", lambda s: None)
    return Downloader(**kw)


def item(url, tmp_path, sha=SHA, size=SIZE):
    return DownloadItem(url, tmp_path / "m" / "model.safetensors", sha, size, label="model")


def test_full_download_verifies_and_renames(server, tmp_path):
    url = server.add("/f", BODY)
    seen = []
    with make() as d:
        path = d.fetch(item(url, tmp_path), lambda label, done, total: seen.append((done, total)))
    assert path.read_bytes() == BODY
    assert not path.with_name(path.name + ".part").exists()
    assert seen[-1] == (len(BODY), len(BODY))
    assert server.requests[0].range is None


def test_existing_file_is_not_downloaded_again(server, tmp_path):
    url = server.add("/f", BODY)
    it = item(url, tmp_path)
    with make() as d:
        d.fetch(it)
        d.fetch(it)
    assert len(server.requests) == 1


def test_resume_after_interrupted_transfer(server, tmp_path):
    url = server.add("/f", BODY, cut_after=dl.CHUNK + 100)
    sleeps = []
    with make(sleep=sleeps.append) as d:
        path = d.fetch(item(url, tmp_path))
    assert path.read_bytes() == BODY
    first, second = (r.range for r in server.requests)
    # Resumes from what reached the disk (whole chunks), never from byte 0.
    assert first is None
    assert second is not None
    assert 0 < int(second.removeprefix("bytes=").rstrip("-")) <= dl.CHUNK + 100
    assert sleeps == [2.0]


def test_resume_from_part_left_by_previous_run(server, tmp_path):
    url = server.add("/f", BODY)
    it = item(url, tmp_path)
    it.part.parent.mkdir(parents=True)
    it.part.write_bytes(BODY[:5000])
    assert Downloader.remaining(it) == len(BODY) - 5000
    with make() as d:
        d.fetch(it)
    assert it.dest.read_bytes() == BODY
    assert server.requests[0].range == "bytes=5000-"


def test_complete_part_is_verified_without_a_request(server, tmp_path):
    url = server.add("/f", BODY)
    it = item(url, tmp_path)
    it.part.parent.mkdir(parents=True)
    it.part.write_bytes(BODY)
    with make() as d:
        d.fetch(it)
    assert it.dest.exists() and server.requests == []


def test_server_ignoring_range_restarts_from_zero(server, tmp_path):
    url = server.add("/f", BODY, ignore_range=True)
    it = item(url, tmp_path)
    it.part.parent.mkdir(parents=True)
    it.part.write_bytes(b"garbage!" * 10)
    with make() as d:
        d.fetch(it)
    assert it.dest.read_bytes() == BODY


def test_oversized_or_bad_part_is_discarded(server, tmp_path):
    url = server.add("/f", BODY)
    it = item(url, tmp_path)
    it.part.parent.mkdir(parents=True)
    it.part.write_bytes(b"x" * (len(BODY) + 5))
    assert Downloader.remaining(it) == len(BODY)
    with make() as d:
        d.fetch(it)
    assert it.dest.read_bytes() == BODY


def test_hash_mismatch_deletes_part_and_fails(server, tmp_path):
    url = server.add("/f", BODY)
    it = item(url, tmp_path, sha="0" * 64)
    with make() as d, pytest.raises(HashMismatchError, match=r"SHA-256 mismatch.*deleted"):
        d.fetch(it)
    assert not it.part.exists() and not it.dest.exists()


def test_more_bytes_than_manifest_size_fails(server, tmp_path):
    url = server.add("/f", BODY)
    it = item(url, tmp_path, size=len(BODY) - 10)
    with make() as d, pytest.raises(HashMismatchError, match="more data"):
        d.fetch(it)
    assert not it.part.exists()


def test_corrupt_resume_prefix_fails_hash(server, tmp_path):
    url = server.add("/f", BODY)
    it = item(url, tmp_path)
    it.part.parent.mkdir(parents=True)
    it.part.write_bytes(b"\0" * 4096)  # right length range, wrong bytes
    with make() as d, pytest.raises(HashMismatchError):
        d.fetch(it)
    assert not it.part.exists()


def test_token_sent_to_own_host_only_and_dropped_on_redirect(server, tmp_path):
    target = server.add("/cdn/f", BODY)
    cdn = target.replace("127.0.0.1", "localhost")
    url = server.add("/f", redirect=cdn)
    with make(tokens={"127.0.0.1": "secret-token"}) as d:
        d.fetch(item(url, tmp_path))
    first, second = server.requests
    assert first.authorization == "Bearer secret-token"
    assert second.host.startswith("localhost") and second.authorization is None


def test_relative_redirect_keeps_host(server, tmp_path):
    server.add("/real", BODY)
    url = server.add("/f", redirect="/real")
    with make(tokens={"127.0.0.1": "t"}) as d:
        d.fetch(item(url, tmp_path))
    assert [r.authorization for r in server.requests] == ["Bearer t", "Bearer t"]


def test_redirect_loop_gives_up(server, tmp_path):
    url = server.add("/f", redirect="/f")
    with make() as d, pytest.raises(DownloadError, match="too many redirects"):
        d.fetch(item(url, tmp_path))


def test_redirect_to_plain_http_elsewhere_is_refused(server, tmp_path):
    url = server.add("/f", redirect="http://example.invalid/x")
    with make() as d, pytest.raises(DownloadError, match="non-HTTPS"):
        d.fetch(item(url, tmp_path))


def test_https_only(tmp_path):
    with make(insecure_hosts=[]) as d, pytest.raises(DownloadError, match="non-HTTPS"):
        d.fetch(item("http://127.0.0.1:1/f", tmp_path))
    with pytest.raises(ValueError, match="loopback"):
        Downloader(insecure_hosts=["example.com"])


def test_retries_transient_errors_with_backoff(server, tmp_path):
    url = server.add("/f", BODY, status=503, fail_times=2)
    sleeps = []
    with make(sleep=sleeps.append, backoff=1.0) as d:
        d.fetch(item(url, tmp_path))
    assert sleeps == [1.0, 2.0]


def test_gives_up_after_retries(server, tmp_path):
    url = server.add("/f", BODY, status=500)
    with make(retries=2) as d, pytest.raises(DownloadError, match=r"kept failing.*resumes"):
        d.fetch(item(url, tmp_path))
    assert len(server.requests) == 3


@pytest.mark.parametrize(
    ("code", "message"), [(401, "needs a login"), (403, "needs a login"), (404, "no longer")]
)
def test_client_errors_are_plain_english(server, tmp_path, code, message):
    url = server.add("/f", status=code)
    with make() as d, pytest.raises(DownloadError, match=message):
        d.fetch(item(url, tmp_path))
    assert len(server.requests) == 1


def test_unexpected_status(server, tmp_path):
    url = server.add("/f", status=204)
    with make() as d, pytest.raises(DownloadError, match="unexpected HTTP 204"):
        d.fetch(item(url, tmp_path))


def test_connection_refused_is_retried_then_fails(tmp_path):
    with make(retries=1) as d, pytest.raises(DownloadError, match="kept failing"):
        d.fetch(item("http://127.0.0.1:9/f", tmp_path))


def test_disk_space_check_before_start(server, tmp_path):
    url = server.add("/f", BODY)
    with (
        make(free_space=lambda p: dl.SPACE_MARGIN) as d,
        pytest.raises(DiskSpaceError, match="Not enough disk space"),
    ):
        d.fetch_all([item(url, tmp_path)])
    assert server.requests == []


def test_disk_full_during_download_keeps_part(server, tmp_path, monkeypatch):
    url = server.add("/f", BODY)
    calls = {"n": 0}
    real = dl._write

    def full(f, block):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError(errno.ENOSPC, "No space left on device")
        real(f, block)

    monkeypatch.setattr(dl, "_write", full)
    it = item(url, tmp_path)
    with make() as d, pytest.raises(DiskSpaceError, match=r"filled up.*resumes"):
        d.fetch(it)
    assert it.part.stat().st_size == dl.CHUNK


def test_other_write_errors_propagate(server, tmp_path, monkeypatch):
    url = server.add("/f", BODY)

    def broken(f, block):
        raise OSError(errno.EIO, "I/O error")

    monkeypatch.setattr(dl, "_write", broken)
    with make() as d, pytest.raises(OSError, match="I/O"):
        d.fetch(item(url, tmp_path))


def test_fetch_all_parallel_and_per_host_limit(server, tmp_path):
    bodies = {f"/f{i}": os.urandom(5000 + i) for i in range(5)}
    items = [
        DownloadItem(
            server.add(p, b), tmp_path / p.strip("/"), hashlib.sha256(b).hexdigest(), len(b)
        )
        for p, b in bodies.items()
    ]
    with make(per_host=1) as d:
        paths = d.fetch_all(items, workers=3)
    assert [p.read_bytes() for p in paths] == list(bodies.values())


def test_unknown_size_and_hash_for_user_urls(server, tmp_path):
    url = server.add("/f", BODY)
    with make() as d:
        path = d.fetch(DownloadItem(url, tmp_path / "x.safetensors", None, None))
    assert path.read_bytes() == BODY


def test_load_tokens(tmp_path):
    p = tmp_path / "secrets.toml"
    assert load_tokens(p) == {}
    p.write_text('[tokens]\n"HuggingFace.co" = "hf_x"\n')
    p.chmod(0o644)
    with pytest.raises(SecretsError, match="chmod 600"):
        load_tokens(p)
    p.chmod(0o600)
    assert load_tokens(p) == {"huggingface.co": "hf_x"}
    p.write_text("[tokens]\nx = 1\n")
    with pytest.raises(SecretsError, match="map host names"):
        load_tokens(p)
    p.write_text("not toml [")
    with pytest.raises(SecretsError, match="not valid TOML"):
        load_tokens(p)


def test_default_secrets_location(tmp_path):
    assert dl.secrets_file() == tmp_path / "config" / "secrets.toml"


def test_token_never_in_error_messages(server, tmp_path):
    url = server.add("/f", status=403)
    with make(tokens={"127.0.0.1": "hf_supersecret"}) as d, pytest.raises(DownloadError) as exc:
        d.fetch(item(url, tmp_path))
    assert "hf_supersecret" not in str(exc.value)


def test_human_size():
    assert human_size(512) == "512 B"
    assert human_size(29_590_440) == "29.6 MB"
    assert human_size(14_407_645_302) == "14.4 GB"
    assert human_size(2 * 10**13) == "20000.0 GB"


def test_content_range_parsing():
    assert dl._content_range_start("bytes 10-19/20") == 10
    assert dl._content_range_start("items 1-2/3") is None
    assert dl._content_range_start("garbage") is None
