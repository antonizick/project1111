"""Run metadata: the sidecar ``.json`` and the recipe embedded in the PNG (spec R7).

A ``RunRecord`` holds what produced an image: the recipe, the bindings (file references, never file
contents), the seed used, model hashes, engine version, timings and step outputs. It is written as a
sidecar next to the image and embedded in PNG ``iTXt`` chunks (``p11:recipe``, ``p11:run``), so an
image dragged back into P11 re-opens as its recipe. ``strip_metadata`` returns the PNG without any
text, EXIF or time chunks (also ComfyUI's ``prompt``/``workflow``) for export.

PNG chunks are edited in the byte stream, so pixels are never re-encoded.
"""

from __future__ import annotations

import json
import os
import struct
import zlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from ..recipe.migrate import migrate
from ..recipe.model import FileRef, Recipe

RECORD_VERSION = 1
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
KEY_RECIPE = "p11:recipe"
KEY_RUN = "p11:run"
#: Ancillary chunks kept by ``strip_metadata``: colour and transparency, nothing descriptive.
SAFE_CHUNKS = frozenset(
    {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"cHRM", b"gAMA", b"iCCP", b"sBIT", b"sRGB",
     b"bKGD", b"pHYs"}
)  # fmt: skip


class MetadataError(ValueError):
    pass


class StepOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    step_index: int = Field(ge=0)
    step_type: str
    #: Path relative to the outputs root.
    path: str
    width: int | None = None
    height: int | None = None


class RunRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    record_version: int = RECORD_VERSION
    recipe: Recipe
    bindings: dict[str, str | FileRef] = Field(default_factory=dict)
    seed: int = Field(ge=0)
    model_hashes: dict[str, str | None] = Field(default_factory=dict)
    engine_version: str = ""
    p11_version: str = ""
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    timings: dict[str, float] = Field(default_factory=dict)
    step_outputs: tuple[StepOutput, ...] = ()
    #: Template slug the run came from; ``None`` for an ad-hoc generation.
    template: str | None = None
    #: Relative path of the image this one was made from (variation, edit), if any.
    parent: str | None = None
    #: The run carried a person's likeness (a face swap or a face reference, or an input made by
    #: one): later edits of these images are checked by the S5 guard too (ADR-0037).
    likeness: bool = False

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)

    @classmethod
    def from_json(cls, text: str | bytes) -> RunRecord:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise MetadataError("run record must be a JSON object")
        if data.get("record_version", 0) > RECORD_VERSION:
            raise MetadataError("This image was made by a newer P11; update P11 to read it.")
        data["recipe"] = migrate(data.get("recipe") or {}).model_dump(mode="json")
        return cls.model_validate(data)


# ---------------------------------------------------------------------------------------------
# Sidecar


def sidecar_path(image: Path) -> Path:
    return image.with_suffix(".json")


def write_sidecar(image: Path, record: RunRecord) -> Path:
    """Write ``<image>.json`` atomically, ``0600``."""
    path = sidecar_path(image)
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(record.to_json())
        fh.write("\n")
    tmp.replace(path)
    return path


def read_sidecar(path: Path) -> RunRecord:
    return RunRecord.from_json(path.read_bytes())


# ---------------------------------------------------------------------------------------------
# PNG chunks


def _chunks(data: bytes) -> Iterator[tuple[bytes, bytes]]:
    if not data.startswith(PNG_SIGNATURE):
        raise MetadataError("not a PNG file")
    pos = len(PNG_SIGNATURE)
    while pos < len(data):
        if pos + 8 > len(data):
            raise MetadataError("truncated PNG chunk header")
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        ctype = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        if len(body) != length or pos + 12 + length > len(data):
            raise MetadataError("truncated PNG chunk")
        (crc,) = struct.unpack(">I", data[pos + 8 + length : pos + 12 + length])
        if zlib.crc32(ctype + body) != crc:
            raise MetadataError(f"bad CRC in PNG chunk {ctype!r}")
        yield ctype, body
        pos += 12 + length
        if ctype == b"IEND":
            return
    raise MetadataError("PNG has no IEND chunk")


def _chunk(ctype: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + ctype + body + struct.pack(">I", zlib.crc32(ctype + body))


def _itxt(key: str, text: str) -> bytes:
    # keyword, NUL, compression flag 1, method 0, empty language tag, NUL, empty translated, NUL
    body = key.encode("latin-1") + b"\x00\x01\x00\x00\x00" + zlib.compress(text.encode(), 9)
    return _chunk(b"iTXt", body)


def _parse_itxt(body: bytes) -> tuple[str, str]:
    key, rest = body.split(b"\x00", 1)
    flag, method = rest[0], rest[1]
    _lang, rest = rest[2:].split(b"\x00", 1)
    _translated, text = rest.split(b"\x00", 1)
    if flag == 1:
        if method != 0:
            raise MetadataError("unknown iTXt compression method")
        text = zlib.decompress(text)
    return key.decode("latin-1"), text.decode("utf-8")


def text_chunks(data: bytes) -> dict[str, str]:
    """All ``tEXt``, ``zTXt`` and ``iTXt`` entries of a PNG."""
    out: dict[str, str] = {}
    for ctype, body in _chunks(data):
        if ctype == b"tEXt":
            key, _, value = body.partition(b"\x00")
            out[key.decode("latin-1")] = value.decode("latin-1")
        elif ctype == b"zTXt":
            key, _, rest = body.partition(b"\x00")
            out[key.decode("latin-1")] = zlib.decompress(rest[1:]).decode("latin-1")
        elif ctype == b"iTXt":
            key_s, value_s = _parse_itxt(body)
            out[key_s] = value_s
    return out


def embed(data: bytes, entries: dict[str, str]) -> bytes:
    """Return ``data`` with ``entries`` as iTXt chunks before ``IEND`` (same keys replaced)."""
    keys = {k.encode("latin-1") for k in entries}
    parts = [PNG_SIGNATURE]
    for ctype, body in _chunks(data):
        if ctype == b"iTXt" and body.split(b"\x00", 1)[0] in keys:
            continue
        if ctype == b"IEND":
            parts.extend(_itxt(k, v) for k, v in sorted(entries.items()))
        parts.append(_chunk(ctype, body))
    return b"".join(parts)


def embed_record(path: Path, record: RunRecord) -> None:
    """Embed the recipe and run record into the PNG at ``path`` (rewritten atomically)."""
    data = embed(
        path.read_bytes(),
        {KEY_RECIPE: record.recipe.model_dump_json(), KEY_RUN: record.model_dump_json()},
    )
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    tmp.replace(path)


def read_recipe_from_png(path: Path) -> Recipe:
    """The recipe embedded by P11, migrated to the current schema."""
    entries = text_chunks(path.read_bytes())
    if KEY_RECIPE not in entries:
        raise MetadataError("This image has no P11 recipe in it.")
    data: Any = json.loads(entries[KEY_RECIPE])
    return migrate(data)


def read_run_from_png(path: Path) -> RunRecord:
    entries = text_chunks(path.read_bytes())
    if KEY_RUN not in entries:
        raise MetadataError("This image has no P11 run record in it.")
    return RunRecord.from_json(entries[KEY_RUN])


def strip_metadata(path: Path) -> bytes:
    """The PNG at ``path`` without text, EXIF, time or private chunks, for export (R7)."""
    parts = [PNG_SIGNATURE]
    parts.extend(_chunk(t, b) for t, b in _chunks(path.read_bytes()) if t in SAFE_CHUNKS)
    return b"".join(parts)
