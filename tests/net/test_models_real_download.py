"""Real downloads from the models' original host. Opt-in: ``P11_NET_TESTS=1`` (needs network)."""

import os

import pytest

from p11.models.download import Downloader
from p11.models.manifest import load_manifest
from p11.models.registry import ModelManager

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(os.environ.get("P11_NET_TESTS") != "1", reason="set P11_NET_TESTS=1"),
]


def test_smallest_default_entry_downloads_and_verifies(tmp_path):
    manifest = load_manifest()
    entry = min(manifest.in_set("default"), key=lambda e: e.size)
    mgr = ModelManager(tmp_path / "models", manifest)
    with Downloader() as dl:
        report = mgr.install(entry.id, downloader=dl, accept_licences=True)
    assert report.downloaded == [entry.id]
    assert report.bytes_downloaded == entry.size
    assert mgr.verify([entry.id])[0].state == "installed"
