import pickle
import struct
import zipfile

import pytest
from tests.fixtures.model_server import safetensors_bytes

from p11.models import formats


class Payload:
    """What a malicious pickle looks like: it calls something on load."""

    def __reduce__(self):
        return (print, ("pwned",))


def write(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_safetensors_detected_by_content_not_extension(tmp_path):
    p = write(tmp_path, "model.ckpt", safetensors_bytes({"encoder.x": 4, "decoder.y": 4}))
    assert formats.sniff(p) == "safetensors"
    assert formats.detect(formats.read_safetensors_header(p)) == ("vae", None)


def test_crafted_pickle_is_identified(tmp_path):
    for proto in (2, 3, 4, 5):
        p = write(tmp_path, f"evil{proto}.safetensors", pickle.dumps(Payload(), protocol=proto))
        assert formats.sniff(p) == "pickle"


def test_torch_zip_pickle(tmp_path):
    p = tmp_path / "model.pt"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("archive/data.pkl", pickle.dumps({"a": 1}))
    assert formats.sniff(p) == "torch-zip"
    q = tmp_path / "plain.zip"
    with zipfile.ZipFile(q, "w") as z:
        z.writestr("readme.txt", "hi")
    assert formats.sniff(q) == "unknown"
    assert formats.sniff(write(tmp_path, "bad.zip", b"PK\x03\x04garbage")) == "unknown"


def test_gguf_and_unknown(tmp_path):
    assert formats.sniff(write(tmp_path, "m.gguf", b"GGUF" + b"\0" * 20)) == "gguf"
    assert formats.sniff(write(tmp_path, "x", b"hello world, not a model")) == "unknown"
    assert formats.sniff(write(tmp_path, "e", b"")) == "unknown"


def test_broken_safetensors(tmp_path):
    p = write(tmp_path, "b.safetensors", struct.pack("<Q", 10) + b"{not json!")
    assert formats.sniff(p) == "unknown"
    with pytest.raises(formats.FormatError, match="not JSON"):
        formats.read_safetensors_header(p)
    with pytest.raises(formats.FormatError, match="too short"):
        formats.read_safetensors_header(write(tmp_path, "s", b"abc"))
    with pytest.raises(formats.FormatError, match="implausible"):
        formats.read_safetensors_header(write(tmp_path, "h", struct.pack("<Q", 10**12) + b"{}"))
    with pytest.raises(formats.FormatError, match="not an object"):
        formats.read_safetensors_header(write(tmp_path, "l", struct.pack("<Q", 2) + b"[]"))


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        (["model.diffusion_model.a", "conditioner.embedders.1.model.x"], ("checkpoint", "sdxl")),
        (["model.diffusion_model.a", "cond_stage_model.transformer.x"], ("checkpoint", "sd15")),
        (["model.diffusion_model.a"], ("checkpoint", None)),
        (["lora_unet_down.lora_up.weight", "lora_te2_x.alpha"], ("lora", "sdxl")),
        (["lora_unet_down.lora_up.weight", "lora_te_x.alpha"], ("lora", "sd15")),
        (["unet.down.lora_A.weight"], ("lora", None)),
        (["encoder.conv", "decoder.conv"], ("vae", None)),
        (["feats.0.weight"], (None, None)),
        ([], (None, None)),
    ],
)
def test_detect(keys, expected):
    header = {k: {} for k in keys} | {"__metadata__": {}}
    assert formats.detect(header) == expected
