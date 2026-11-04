"""Rebuild the upload fuzz corpus (Phase 16, spec S8). Every file is synthetic: generated here.

    uv run python tests/fixtures/fuzz/make_corpus.py

Hand-made malformed images and videos that the upload validator must refuse cleanly (or accept and
re-encode), never crash on. ``tests/unit/test_upload_fuzz.py`` runs them plus seeded random
mutations of small valid files.
"""

from __future__ import annotations

import io
import shutil
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent


def png(size=(8, 8), mode="RGB", **kw) -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, 128 if mode in ("L", "P", "I;16", "I") else (10, 120, 200)).save(
        buf, format="PNG", **kw
    )
    return buf.getvalue()


def chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def png_header(w: int, h: int, *, bit_depth=8, colour=2) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + chunk(
        b"IHDR", struct.pack(">IIBBBBB", w, h, bit_depth, colour, 0, 0, 0)
    )


def jpeg(size=(16, 16), mode="RGB") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, (200, 50, 50) if mode == "RGB" else (0, 50, 50, 0)).save(
        buf, format="JPEG"
    )
    return buf.getvalue()


def webp(size=(16, 16)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (20, 200, 20)).save(buf, format="WEBP")
    return buf.getvalue()


def images() -> dict[str, bytes]:
    good = png()
    idat_start = good.index(b"IDAT") - 4
    return {
        "empty.png": b"",
        "magic-only.png": b"\x89PNG\r\n\x1a\n",
        "truncated-ihdr.png": good[:20],
        "truncated-idat.png": good[: idat_start + 12],
        "bad-crc.png": good[:29] + b"\x00\x00\x00\x00" + good[33:],
        "zero-size.png": png_header(0, 0) + chunk(b"IEND", b""),
        "huge-dimensions.png": png_header(100_000, 100_000)
        + chunk(b"IDAT", zlib.compress(b"\x00" * 64))
        + chunk(b"IEND", b""),
        "wide-strip.png": png_header(20_000, 1)
        + chunk(b"IDAT", zlib.compress(b"\x00" * 64))
        + chunk(b"IEND", b""),
        "bad-bit-depth.png": png_header(4, 4, bit_depth=7) + chunk(b"IEND", b""),
        "idat-zip-bomb.png": png_header(64, 64)
        + chunk(b"IDAT", zlib.compress(b"\x00" * 50_000_000))
        + chunk(b"IEND", b""),
        "text-zip-bomb.png": good[:33]
        + chunk(b"zTXt", b"k\x00\x00" + zlib.compress(b"A" * 20_000_000))
        + good[33:],
        "sixteen-bit.png": png(mode="I;16"),
        "palette-transparency.png": png(mode="P", transparency=0),
        "png-named-jpeg.jpg": good,
        "truncated.jpg": jpeg()[:60],
        "no-eoi.jpg": jpeg()[:-2],
        "cmyk.jpg": jpeg(mode="CMYK"),
        "garbage-after-soi.jpg": b"\xff\xd8" + bytes(range(256)) * 4,
        "truncated.webp": webp()[:30],
        "riff-not-webp.webp": b"RIFF\x10\x00\x00\x00WAVEfmt " + b"\x00" * 8,
        "gif.gif": _gif(),
        "svg.svg": b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        "html.png": b"<html><img src=x onerror=alert(1)></html>",
        "elf.png": b"\x7fELF" + b"\x00" * 60,
    }


def _gif() -> bytes:
    buf = io.BytesIO()
    Image.new("P", (4, 4)).save(buf, format="GIF")
    return buf.getvalue()


def videos(tmp: Path) -> dict[str, bytes]:
    src = tmp / "ok.mp4"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
         "testsrc=size=64x48:rate=5:duration=0.6", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         str(src)],
        check=True,
    )  # fmt: skip
    ok = src.read_bytes()
    wav = tmp / "a.wav"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "sine=duration=0.3", str(wav)], check=True)  # fmt: skip
    moov = ok.find(b"moov")
    return {
        "ok.mp4": ok,
        "empty.mp4": b"",
        "ftyp-only.mp4": ok[:32],
        "half.mp4": ok[: len(ok) // 2],
        "no-moov.mp4": ok[: moov - 4] if moov > 4 else ok[:16],
        "zeroed-moov.mp4": ok[:moov] + b"\x00" * (len(ok) - moov) if moov > 0 else ok,
        "audio-only.wav": wav.read_bytes(),
        "png-named.mp4": png(),
        "text.mp4": b"#EXTM3U\n#EXT-X-STREAM-INF:\nhttp://example.invalid/x.m3u8\n",
        "concat-list.mp4": b"ffconcat version 1.0\nfile '/etc/passwd'\n",
    }


def main() -> None:
    for name, data in images().items():
        (HERE / "images" / name).parent.mkdir(exist_ok=True)
        (HERE / "images" / name).write_bytes(data)
    if shutil.which("ffmpeg"):
        with tempfile.TemporaryDirectory() as t:
            for name, data in videos(Path(t)).items():
                (HERE / "videos").mkdir(exist_ok=True)
                (HERE / "videos" / name).write_bytes(data)
    print("corpus written to", HERE)


if __name__ == "__main__":
    main()
