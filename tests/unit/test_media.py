"""Upload validation (S8) and the input store (S6): synthetic files only."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image
from tests.studio import png_bytes, studio_client

from p11.media import validate
from p11.media.inputs import InputStore, UnknownInput
from p11.media.validate import UploadRejected, check_video, validate_image

needs_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed"
)


def jpeg_with_gps() -> bytes:
    img = Image.new("RGB", (40, 30), "orange")
    exif = Image.Exif()
    exif[0x010F] = "SyntheticCam"  # Make
    exif[0x0112] = 6  # Orientation: rotate 90° CW
    gps = exif.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = (48.0, 51.0, 30.0)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def test_png_is_reencoded_without_text():
    from PIL.PngImagePlugin import PngInfo

    info = PngInfo()
    info.add_text("Comment", "private note")
    out = validate_image(png_bytes(pnginfo=info))
    assert out.source_format == "PNG" and (out.width, out.height) == (64, 48)
    with Image.open(io.BytesIO(out.png)) as img:
        assert "Comment" not in img.info and img.format == "PNG"


def test_jpeg_exif_and_gps_are_stripped_and_orientation_applied():
    data = jpeg_with_gps()
    with Image.open(io.BytesIO(data)) as src:
        assert src.getexif().get_ifd(0x8825)  # the fixture really has GPS
    out = validate_image(data)
    assert (out.width, out.height) == (30, 40)  # turned upright
    assert b"Exif" not in out.png and b"SyntheticCam" not in out.png
    with Image.open(io.BytesIO(out.png)) as img:
        assert not img.getexif()


@pytest.mark.parametrize(
    "data",
    [
        b"#!/bin/sh\necho not an image\n",
        b"\x89PNG\r\n\x1a\n" + b"\0" * 40,  # a PNG signature with garbage after it
        png_bytes()[:60],  # truncated
    ],
)
def test_non_images_are_refused_whatever_their_name(data):
    with pytest.raises(UploadRejected, match=r"not a readable image|not a PNG"):
        validate_image(data)


def test_other_formats_are_refused():
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, format="GIF")
    with pytest.raises(UploadRejected, match="not a PNG, JPEG or WebP"):
        validate_image(buf.getvalue())


def test_pixel_and_byte_caps(monkeypatch):
    monkeypatch.setattr(validate, "MAX_PIXELS", 1000)
    with pytest.raises(UploadRejected, match="too large"):
        validate_image(png_bytes((50, 50)))
    monkeypatch.setattr(validate, "MAX_IMAGE_BYTES", 10)
    with pytest.raises(UploadRejected, match="larger than"):
        validate_image(png_bytes())


def test_mask_becomes_greyscale():
    out = validate_image(png_bytes(), kind="mask")
    with Image.open(io.BytesIO(out.png)) as img:
        assert img.mode == "L"


def test_store_generates_names_and_private_modes(tmp_path):
    store = InputStore(tmp_path / "inputs")
    item = store.add_image(png_bytes())
    assert item.id.startswith("img-") and item.path.name == f"{item.id}.png"
    assert (tmp_path / "inputs").stat().st_mode & 0o777 == 0o700
    assert item.path.stat().st_mode & 0o777 == 0o600
    assert store.get(item.id) == item
    assert item.as_json()["kind"] == "image" and "path" not in item.as_json()


@pytest.mark.parametrize(
    "bad", ["../etc/passwd", "img-../../x", "img-" + "0" * 31, "vid-" + "g" * 32, "img-0/../x"]
)
def test_store_refuses_path_like_ids(tmp_path, bad):
    with pytest.raises(UnknownInput):
        InputStore(tmp_path).get(bad)


def test_store_missing_file(tmp_path):
    store = InputStore(tmp_path)
    item = store.add_image(png_bytes())
    item.path.unlink()
    with pytest.raises(UnknownInput, match="gone"):
        store.get(item.id)
    with pytest.raises(UnknownInput):
        store.get("img-" + "a" * 32)


# -- video --------------------------------------------------------------------------------------


def probe(container="mov,mp4,m4a,3gp,3g2,mj2", codec="h264", seconds=5.0, w=1280, h=720,
          audio="aac"):  # fmt: skip
    streams = [{"codec_type": "video", "codec_name": codec, "width": w, "height": h,
                "avg_frame_rate": "30000/1001"}]  # fmt: skip
    if audio:
        streams.append({"codec_type": "audio", "codec_name": audio})
    return {"format": {"format_name": container, "duration": str(seconds)}, "streams": streams}


def test_check_video_allowlists_and_caps():
    info = check_video(probe())
    assert (info.container, info.codec, info.width, info.height) == ("mp4", "h264", 1280, 720)
    assert round(info.fps, 2) == 29.97 and info.warnings == ()
    with pytest.raises(UploadRejected, match="container"):
        check_video(probe(container="avi"))
    with pytest.raises(UploadRejected, match="codec"):
        check_video(probe(codec="prores"))
    with pytest.raises(UploadRejected, match="audio codec"):
        check_video(probe(audio="dts"))
    with pytest.raises(UploadRejected, match="at most 600"):
        check_video(probe(seconds=601))
    with pytest.raises(UploadRejected, match="2160p"):
        check_video(probe(w=7680, h=4320))
    with pytest.raises(UploadRejected, match="no video track"):
        check_video({"format": {"format_name": "matroska,webm"}, "streams": []})
    with pytest.raises(UploadRejected, match="cannot be read"):
        check_video(probe(seconds=0))


def test_r13_limits_only_warn():
    info = check_video(probe(seconds=90, w=2560, h=1440))
    assert len(info.warnings) == 2
    assert check_video(probe(seconds=90), warn_seconds=120).warnings == ()


def _make_video(path: Path, *, location: bool = True, seconds: float = 1.0) -> None:
    args = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
            f"testsrc=size=160x120:rate=10:duration={seconds}", "-f", "lavfi", "-i",
            f"sine=frequency=440:duration={seconds}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest"]  # fmt: skip
    if location:
        args += ["-metadata", "location=+48.8577+002.2950/", "-metadata", "title=private"]
    subprocess.run([*args, str(path)], check=True, capture_output=True)


def _tags(path: Path) -> dict[str, str]:
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format",
                          str(path)], capture_output=True, check=True)  # fmt: skip
    return dict(json.loads(out.stdout)["format"].get("tags", {}))


@needs_ffmpeg
def test_video_is_validated_and_stored_without_metadata(tmp_path):
    src = tmp_path / "clip.mp4"
    _make_video(src)
    assert "location" in _tags(src)
    store = InputStore(tmp_path / "inputs")
    item = store.add_video(src)
    assert item.kind == "video" and item.id.startswith("vid-") and item.path.suffix == ".mp4"
    assert (item.width, item.height) == (160, 120) and item.seconds and item.seconds > 0.5
    tags = _tags(item.path)
    assert "location" not in tags and "title" not in tags
    assert item.path.stat().st_mode & 0o777 == 0o600
    assert store.get(item.id).seconds == item.seconds


@needs_ffmpeg
def test_non_video_is_refused_by_ffprobe(tmp_path):
    fake = tmp_path / "movie.mp4"
    fake.write_bytes(b"not a video at all" * 100)
    with pytest.raises(UploadRejected, match="not a readable video"):
        InputStore(tmp_path / "inputs").add_video(fake)


# -- route --------------------------------------------------------------------------------------


def test_upload_route_image_and_errors(tmp_path):
    with studio_client(tmp_path) as c:
        r = c.post("/api/uploads", headers=c.auth, content=jpeg_with_gps())
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["kind"] == "image" and (body["width"], body["height"]) == (30, 40)
        got = c.get(f"/api/uploads/{body['id']}", headers=c.auth)
        assert got.headers["content-type"] == "image/png" and b"Exif" not in got.content
        assert c.get(f"/api/uploads/{body['id']}/info", headers=c.auth).json() == body
        bad = c.post("/api/uploads", headers=c.auth, content=b"<svg onload=alert(1)>")
        assert bad.status_code == 422 and bad.json()["code"] == "upload.rejected"
        empty = c.post("/api/uploads", headers=c.auth, content=b"")
        assert empty.status_code == 422
        mask = c.post("/api/uploads?kind=mask", headers=c.auth, content=png_bytes())
        assert mask.json()["kind"] == "mask"
        assert c.get("/api/uploads/img-nothere", headers=c.auth).status_code == 404
        assert c.get("/api/uploads/..%2F..%2Fetc%2Fpasswd", headers=c.auth).status_code == 404
        assert c.post("/api/uploads?kind=pdf", headers=c.auth, content=b"x").status_code == 422


def test_upload_route_image_too_big(tmp_path, monkeypatch):
    from p11.api.routes import uploads

    monkeypatch.setattr(uploads, "MAX_IMAGE_BYTES", 100)
    with studio_client(tmp_path) as c:
        r = c.post("/api/uploads", headers=c.auth, content=png_bytes((200, 200), "red"))
        assert r.status_code == 422 and "larger than" in r.json()["message"]


@needs_ffmpeg
def test_upload_route_video(tmp_path, monkeypatch):
    from p11.api.routes import uploads

    src = tmp_path / "clip.mp4"
    _make_video(src)
    with studio_client(tmp_path, video_warn_seconds=0.5) as c:
        r = c.post("/api/uploads?kind=video", headers=c.auth, content=src.read_bytes())
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["kind"] == "video" and body["warnings"]
        assert c.get(f"/api/uploads/{body['id']}", headers=c.auth).headers["content-type"] == (
            "video/mp4"
        )
        assert not list((tmp_path / "data" / "inputs" / ".incoming").iterdir())
        monkeypatch.setattr(uploads, "MAX_VIDEO_BYTES", 10)
        big = c.post("/api/uploads?kind=video", headers=c.auth, content=src.read_bytes())
        assert big.status_code == 422
        empty = c.post("/api/uploads?kind=video", headers=c.auth, content=b"")
        assert empty.status_code == 422
