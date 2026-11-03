# ruff: noqa: E501  (TOML test data reads best unwrapped)
import itertools
import re
from pathlib import Path

import pytest

from p11.models.manifest import (
    KIND_FOLDERS,
    ManifestError,
    find_manifest,
    load_manifest,
    parse_manifest,
)
from p11.models.registry import entry_info
from p11.recipe.registry import PROVISIONAL_DEFAULT_SET

REPO_MANIFEST = Path(__file__).resolve().parents[2] / "models" / "manifest.toml"
SHA = "a" * 64

GOOD = f"""
schema_version = 1

[[model]]
id = "ckpt"
name = "Checkpoint"
kind = "checkpoint"
base = "sdxl"
sets = ["default"]
files = [{{ url = "https://example.org/c.safetensors", filename = "c.safetensors", sha256 = "{SHA}", size = 10 }}]
licence = {{ name = "MIT", url = "https://opensource.org/license/mit", commercial_use = true }}
defaults = {{ sampler = "euler", scheduler = "normal", steps = 20, cfg = 5.0, vae = "vae" }}

[[model]]
id = "vae"
name = "VAE"
kind = "vae"
base = "sdxl"
sets = ["default"]
files = [{{ url = "https://example.org/v.safetensors", filename = "v.safetensors", sha256 = "{"b" * 64}", size = 5 }}]
licence = {{ name = "MIT", url = "https://opensource.org/license/mit", commercial_use = true }}
"""


def test_good_manifest():
    m = parse_manifest(GOOD)
    assert [e.id for e in m] == ["ckpt", "vae"]
    assert m.get("ckpt").folder == "checkpoints"
    assert m.in_set("default") == list(m.entries)
    assert m.by_sha256(SHA).id == "ckpt"
    assert m.by_sha256("c" * 64) is None
    assert not m.get("vae").licence.needs_acknowledgement


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('name = "VAE"', 'name = "VAE"\ncolour = "red"', "Extra inputs"),
        ("https://example.org/c", "http://example.org/c", "must be https"),
        (f'sha256 = "{SHA}"', 'sha256 = "ABC"', "64 lower-case hex"),
        ('id = "vae"', 'id = "ckpt"', "duplicate model ids"),
        ('vae = "vae" }', 'vae = "nope" }', "is not a VAE"),
        ('filename = "c.safetensors"', 'filename = "../c.safetensors"', "invalid file name"),
        ('id = "ckpt"', 'id = "Bad ID"', "invalid model id"),
        ('kind = "vae"', 'kind = "pickle"', "kind"),
        ("schema_version = 1", "schema_version = 2", "schema_version"),
        (
            'sets = ["default"]\nfiles',
            'sets = ["default"]\nrequires_login = true\nfiles',
            "login-free",
        ),
        (
            "commercial_use = true }\ndefaults",
            'commercial_use = true, flags = ["non-commercial"] }\ndefaults',
            "non-commercial",
        ),
        ("size = 10", "size = 0", "greater than 0"),
        ('kind = "vae"', 'kind = "upscale"', "'scale' is required"),
        ('kind = "checkpoint"', 'kind = "lora"', "only checkpoints carry"),
        (
            'url = "https://opensource.org/license/mit", commercial_use = true }\ndefaults',
            'url = "http://x", commercial_use = true }\ndefaults',
            "licence URLs must be https",
        ),
    ],
)
def test_bad_manifests(old, new, message):
    assert old in GOOD
    with pytest.raises(ManifestError, match=message):
        parse_manifest(GOOD.replace(old, new, 1))


def test_checkpoint_needs_defaults():
    text = GOOD.split("defaults =")[0] + GOOD.split('vae" }', 1)[1]
    with pytest.raises(ManifestError, match=r"need \[defaults\]"):
        parse_manifest(text)


def test_two_entries_cannot_write_the_same_file():
    second_vae = GOOD.split("[[model]]")[2].replace('id = "vae"', 'id = "vae2"')
    second_vae = second_vae.replace('"' + "b" * 64 + '"', '"' + "c" * 64 + '"')
    with pytest.raises(ManifestError, match="same file"):
        parse_manifest(GOOD + "\n[[model]]" + second_vae)


def test_vae_set_must_cover_checkpoint_sets():
    with pytest.raises(ManifestError, match="its VAE"):
        parse_manifest(
            GOOD.replace('sets = ["default"]', 'sets = ["full"]', 2).replace(
                'sets = ["full"]', 'sets = ["default"]', 1
            )
        )


def test_not_toml_and_unreadable(tmp_path):
    with pytest.raises(ManifestError, match="not valid TOML"):
        parse_manifest("[[model")
    with pytest.raises(ManifestError, match="cannot read"):
        load_manifest(tmp_path / "missing.toml")


def test_find_manifest(monkeypatch, tmp_path):
    assert find_manifest() == REPO_MANIFEST
    monkeypatch.setenv("P11_MODEL_MANIFEST", str(tmp_path / "m.toml"))
    assert find_manifest() == tmp_path / "m.toml"


# -- the shipped manifest -----------------------------------------------------------------------


def test_repo_manifest_is_valid_and_within_budget():
    m = load_manifest(REPO_MANIFEST)
    default = m.in_set("default")
    assert {e.id for e in default} == {
        "realvisxl5-lightning",
        "juggernautxl9",
        "sdxl-vae-fp16-fix",
        "4x-nomos-webphoto-realplksr",
        "birefnet-lite",
    }
    assert sum(e.size for e in default) <= 30 * 1000**3  # owner question 1 / H1
    for e in m:
        assert not e.requires_login  # H2
        assert e.file.url.startswith("https://huggingface.co/")
        assert re.search(r"/resolve/[0-9a-f]{40}/", e.file.url), "URL must pin a commit"
        # S4: tensors-only formats load by default. ONNX (segmentation, face analysis) is
        # executable-proof and curated entries are hash-pinned (S4; Phase 06 note).
        assert e.file.filename.endswith((".safetensors", ".onnx", ".gguf"))
        assert e.kind in KIND_FOLDERS


def test_every_entry_has_a_check_timestamp_comment():
    text = REPO_MANIFEST.read_text()
    blocks = text.split("[[model]]")
    for before, block in itertools.pairwise(blocks):
        model_id = re.search(r'^id = "([^"]+)"', block, re.M).group(1)
        comment = before.strip().splitlines()[-2:]
        assert any(
            re.match(r"# Checked \d{4}-\d{2}-\d{2} \d{2}:\d{2} [A-Z]{3,4}:", line)
            for line in comment
        ), model_id


def test_provisional_registry_matches_manifest():
    """The compiler tests' in-memory registry must be exactly what the manifest says."""
    m = load_manifest(REPO_MANIFEST)
    for e in m:
        assert PROVISIONAL_DEFAULT_SET.get(e.id) == entry_info(e)
    assert all(e.id in PROVISIONAL_DEFAULT_SET for e in m)
