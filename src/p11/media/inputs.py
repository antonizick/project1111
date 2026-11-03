"""Stored uploads (spec S6, S8): ``~/.local/share/p11/inputs/`` with generated names, ``0700``.

An upload is known to the rest of P11 only by its opaque ID (``img-<hex>`` or ``vid-<hex>``),
which is what a recipe's ``FileRef.ref`` holds. The ID is checked against a strict pattern before
it touches the filesystem, so a browser cannot name a path.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from p11 import paths

from .validate import (
    ImageKind,
    UploadRejected,
    check_video,
    probe_video,
    strip_video_metadata,
    validate_image,
)

InputKind = Literal["image", "mask", "video"]
ID_RE = re.compile(r"^(img|vid)-[0-9a-f]{32}$")
_EXT = {"mp4": ".mp4", "matroska": ".mkv"}


class UnknownInput(LookupError):
    pass


@dataclass(frozen=True)
class StoredInput:
    id: str
    kind: InputKind
    path: Path
    width: int
    height: int
    sha256: str
    created_at: str
    seconds: float | None = None
    warnings: tuple[str, ...] = ()

    def as_json(self) -> dict[str, object]:
        out = asdict(self)
        out.pop("path")
        out["warnings"] = list(self.warnings)
        return out


def _write_private(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)


class InputStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or paths.inputs_dir()

    def _ready(self) -> Path:
        return paths.ensure_private_dir(self.root)

    def _meta_path(self, input_id: str) -> Path:
        if not ID_RE.match(input_id):
            raise UnknownInput(f"{input_id!r} is not an upload ID.")
        return self.root / f"{input_id}.json"

    def add_image(self, data: bytes, kind: ImageKind = "image") -> StoredInput:
        valid = validate_image(data, kind)
        root = self._ready()
        input_id = f"img-{uuid.uuid4().hex}"
        path = root / f"{input_id}.png"
        _write_private(path, valid.png)
        item = StoredInput(
            input_id,
            kind,
            path,
            valid.width,
            valid.height,
            valid.sha256,
            datetime.now(UTC).isoformat(timespec="seconds"),
        )
        self._write_meta(item)
        return item

    def add_video(
        self, src: Path, *, warn_seconds: float = 60.0, warn_height: int = 1080
    ) -> StoredInput:
        """Validate the (temporary) file ``src`` and store a metadata-free remux of it."""
        info = check_video(probe_video(src), warn_seconds=warn_seconds, warn_height=warn_height)
        root = self._ready()
        input_id = f"vid-{uuid.uuid4().hex}"
        dest = root / f"{input_id}{_EXT[info.container]}"
        tmp = root / f".{input_id}.tmp"
        try:
            strip_video_metadata(src, tmp, info.container)
            os.chmod(tmp, 0o600)
            # The remux must still be the video we checked (it is a copy, so this is cheap).
            check_video(probe_video(tmp), warn_seconds=warn_seconds, warn_height=warn_height)
            tmp.replace(dest)
        finally:
            tmp.unlink(missing_ok=True)
        digest = hashlib.sha256()
        with dest.open("rb") as fh:
            for block in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(block)
        item = StoredInput(
            input_id,
            "video",
            dest,
            info.width,
            info.height,
            digest.hexdigest(),
            datetime.now(UTC).isoformat(timespec="seconds"),
            seconds=info.seconds,
            warnings=info.warnings,
        )
        self._write_meta(item)
        return item

    def _write_meta(self, item: StoredInput) -> None:
        meta = {**item.as_json(), "file": item.path.name}
        _write_private(self._meta_path(item.id), json.dumps(meta).encode())

    def get(self, input_id: str) -> StoredInput:
        meta_path = self._meta_path(input_id)
        try:
            meta = json.loads(meta_path.read_text())
        except (OSError, ValueError) as exc:
            raise UnknownInput(f"No upload {input_id!r}.") from exc
        path = self.root / str(meta["file"])
        if path.parent != self.root or not path.is_file():
            raise UnknownInput(f"The file of upload {input_id!r} is gone.")
        return StoredInput(
            input_id,
            meta["kind"],
            path,
            int(meta["width"]),
            int(meta["height"]),
            str(meta["sha256"]),
            str(meta["created_at"]),
            seconds=meta.get("seconds"),
            warnings=tuple(meta.get("warnings", ())),
        )

    def spool_dir(self) -> Path:
        """Where an upload in progress is streamed before validation (same disk, private)."""
        return paths.ensure_private_dir(self.root / ".incoming")

    def spool(self) -> tuple[int, Path]:
        fd, name = tempfile.mkstemp(dir=self.spool_dir(), prefix="up-")
        return fd, Path(name)


__all__ = ["InputKind", "InputStore", "StoredInput", "UnknownInput", "UploadRejected"]
