"""Upload fuzzing (Phase 16, spec S8): malformed images and videos are refused cleanly.

The committed corpus (``tests/fixtures/fuzz/``, synthetic, rebuilt by ``make_corpus.py``) holds
hand-made malformed files; seeded mutations of small valid files add a few hundred more. For every
input the store either accepts it (and what it stored is a clean PNG / a probeable video) or raises
``UploadRejected`` with a plain-English message. Anything else (a Pillow or ffprobe exception
escaping, a hang) is a bug.
"""

from __future__ import annotations

import contextlib
import io
import random
import shutil
from pathlib import Path

import pytest
from PIL import Image

from p11.media.inputs import InputStore
from p11.media.validate import UploadRejected

FUZZ = Path(__file__).resolve().parents[1] / "fixtures" / "fuzz"
IMAGES = sorted((FUZZ / "images").iterdir())
VIDEOS = sorted((FUZZ / "videos").iterdir())
needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffprobe"), reason="ffprobe not installed")


def seeds() -> list[bytes]:
    out = []
    for fmt, mode in (("PNG", "RGBA"), ("JPEG", "RGB"), ("WEBP", "RGB"), ("PNG", "P")):
        buf = io.BytesIO()
        Image.new(mode, (12, 9), 77 if mode == "P" else (1, 2, 3, 4)[: len(mode)]).save(
            buf, format=fmt
        )
        out.append(buf.getvalue())
    return out


def mutate(data: bytes, rng: random.Random) -> bytes:
    b = bytearray(data)
    op = rng.randrange(4)
    if op == 0:  # flip bytes
        for _ in range(rng.randint(1, 8)):
            b[rng.randrange(len(b))] = rng.randrange(256)
    elif op == 1:  # truncate
        del b[rng.randrange(1, len(b)) :]
    elif op == 2:  # insert junk
        i = rng.randrange(len(b))
        b[i:i] = rng.randbytes(rng.randint(1, 64))
    else:  # duplicate a slice (chunk confusion)
        i = rng.randrange(len(b))
        b[i:i] = b[i : i + rng.randint(1, 40)]
    return bytes(b)


def store_image(store: InputStore, data: bytes, kind: str = "image") -> None:
    try:
        item = store.add_image(data, kind)  # type: ignore[arg-type]
    except UploadRejected as exc:
        assert str(exc) and "Traceback" not in str(exc)
        return
    with Image.open(item.path) as im:  # what was stored is a clean, decodable PNG
        assert im.format == "PNG"
        im.load()
        assert "exif" not in im.info


@pytest.mark.parametrize("path", IMAGES, ids=lambda p: p.name)
def test_corpus_images_are_refused_or_cleanly_stored(tmp_path, path) -> None:
    store = InputStore(tmp_path / "in")
    store_image(store, path.read_bytes())
    store_image(store, path.read_bytes(), "mask")


def test_mutated_images_never_escape_the_validator(tmp_path) -> None:
    store = InputStore(tmp_path / "in")
    rng = random.Random(1611)
    for seed in seeds():
        for _ in range(100):
            store_image(store, mutate(seed, rng))


@needs_ffmpeg
@pytest.mark.parametrize("path", VIDEOS, ids=lambda p: p.name)
def test_corpus_videos_are_refused_or_cleanly_stored(tmp_path, path) -> None:
    store = InputStore(tmp_path / "in")
    src = tmp_path / "upload.bin"
    src.write_bytes(path.read_bytes())
    try:
        item = store.add_video(src)
    except UploadRejected as exc:
        assert str(exc)
        return
    assert item.kind == "video" and item.path.is_file()


@needs_ffmpeg
def test_mutated_videos_never_escape_the_validator(tmp_path) -> None:
    ok = (FUZZ / "videos" / "ok.mp4").read_bytes()
    full = (FUZZ / "videos" / "zeroed-moov.mp4").read_bytes()
    rng = random.Random(1612)
    store = InputStore(tmp_path / "in")
    for i in range(30):
        src = tmp_path / f"m{i}.bin"
        src.write_bytes(mutate(rng.choice([ok, full]), rng))
        with contextlib.suppress(UploadRejected):
            store.add_video(src)
