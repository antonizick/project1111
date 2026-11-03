"""The curated model manifest (``models/manifest.toml``, spec R9, ADR-0006).

Pure schema plus a loader. Every entry is hash-pinned; unknown keys are an error so a typo in the
manifest never silently drops a field.
"""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from p11 import paths

MANIFEST_NAME = "manifest.toml"

Kind = Literal[
    "checkpoint",
    "lora",
    "vae",
    "controlnet",
    "ipadapter",
    "upscale",
    "facerestore",
    "faceswap",
    "facedetect",
    "segmentation",
    "embedding",
]
Base = Literal["sdxl", "sd15", "any"]
SetName = Literal["default", "full", "optional"]
LicenceFlag = Literal[
    "non-commercial",
    "attribution",
    "use-restrictions",
    "share-alike",
    "research-only",
]

#: Folder under the models root per kind (spec R8). ComfyUI reads these through
#: ``extra_model_paths.yaml``; ``facedetect`` is new in Phase 06 for Phase 12's models.
KIND_FOLDERS: dict[str, str] = {
    "checkpoint": "checkpoints",
    "lora": "loras",
    "vae": "vae",
    "controlnet": "controlnet",
    "ipadapter": "ipadapter",
    "upscale": "upscale",
    "facerestore": "facerestore",
    "faceswap": "faceswap",
    "facedetect": "facedetect",
    "segmentation": "segmentation",
    "embedding": "embeddings",
}

_ID = re.compile(r"^[a-z0-9][a-z0-9.-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,199}$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def check_filename(value: str) -> str:
    """A bare file name: no directories, no leading dot, nothing a shell or ComfyUI trips over."""
    if not _FILENAME.match(value) or ".." in value:
        raise ValueError(f"invalid file name {value!r}")
    return value


class ModelFile(_Strict):
    url: str
    filename: Annotated[str, Field(min_length=1)]
    sha256: str
    size: Annotated[int, Field(gt=0)]

    @field_validator("url")
    @classmethod
    def _https(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme != "https" or not parts.hostname:
            raise ValueError(f"model URLs must be https: {value!r}")
        return value

    @field_validator("filename")
    @classmethod
    def _filename(cls, value: str) -> str:
        return check_filename(value)

    @field_validator("sha256")
    @classmethod
    def _sha(cls, value: str) -> str:
        if not _SHA256.match(value):
            raise ValueError("sha256 must be 64 lower-case hex characters")
        return value

    @property
    def host(self) -> str:
        return urlsplit(self.url).hostname or ""


class Licence(_Strict):
    name: Annotated[str, Field(min_length=1)]
    url: str
    #: Whether the licence allows commercial use of outputs and the model (H3: shown everywhere).
    commercial_use: bool
    flags: tuple[LicenceFlag, ...] = ()

    @field_validator("url")
    @classmethod
    def _https(cls, value: str) -> str:
        if urlsplit(value).scheme != "https":
            raise ValueError("licence URLs must be https")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> Licence:
        if self.commercial_use and "non-commercial" in self.flags:
            raise ValueError("a non-commercial licence cannot set commercial_use = true")
        return self

    @property
    def needs_acknowledgement(self) -> bool:
        """Licences with flags need an explicit yes before the first install (Task 4)."""
        return bool(self.flags) or not self.commercial_use


class Defaults(_Strict):
    sampler: str
    scheduler: str
    steps: Annotated[int, Field(ge=1, le=200)]
    cfg: Annotated[float, Field(ge=0, le=30)]
    clip_skip: Annotated[int, Field(ge=1, le=12)] = 1
    #: Steps of the refinement pass in the ``latent``/``both`` chains (Phase 03/04).
    hires_steps: Annotated[int, Field(ge=0, le=200)] = 0
    #: Manifest ID of the VAE to load instead of the baked one; absent = baked VAE.
    vae: str | None = None


class Entry(_Strict):
    id: str
    name: Annotated[str, Field(min_length=1)]
    kind: Kind
    base: Base
    files: Annotated[tuple[ModelFile, ...], Field(min_length=1, max_length=1)]
    licence: Licence
    requires_login: bool = False
    sets: tuple[SetName, ...] = ()
    defaults: Defaults | None = None
    #: Scale factor of an upscale model (4 for a 4x model).
    scale: Annotated[int, Field(ge=1, le=16)] | None = None
    #: Source repository and revision, for humans (the URL carries the pinned revision).
    source: str = ""
    notes: str = ""

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        if not _ID.match(value):
            raise ValueError(f"invalid model id {value!r} (lower-case letters, digits, '.', '-')")
        return value

    @model_validator(mode="after")
    def _shape(self) -> Entry:
        if self.kind == "checkpoint" and self.defaults is None:
            raise ValueError(f"{self.id}: checkpoints need [defaults]")
        if self.kind != "checkpoint" and self.defaults is not None:
            raise ValueError(f"{self.id}: only checkpoints carry [defaults]")
        if (self.kind == "upscale") != (self.scale is not None):
            raise ValueError(f"{self.id}: 'scale' is required for upscalers and only for them")
        if self.requires_login and "default" in self.sets:
            raise ValueError(f"{self.id}: the default set must be login-free (H2)")
        return self

    @property
    def file(self) -> ModelFile:
        return self.files[0]

    @property
    def folder(self) -> str:
        return KIND_FOLDERS[self.kind]

    @property
    def size(self) -> int:
        return sum(f.size for f in self.files)


class Manifest(_Strict):
    schema_version: Literal[1]
    entries: tuple[Entry, ...] = Field(alias="model")
    path: Path | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def _references(self) -> Manifest:
        ids = [e.id for e in self.entries]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate model ids: {', '.join(dupes)}")
        targets = [(e.folder, e.file.filename) for e in self.entries]
        if len(set(targets)) != len(targets):
            raise ValueError("two entries write the same file")
        by_id = {e.id: e for e in self.entries}
        for e in self.entries:
            vae = e.defaults.vae if e.defaults else None
            if vae is None:
                continue
            target = by_id.get(vae)
            if target is None or target.kind != "vae":
                raise ValueError(f"{e.id}: defaults.vae {vae!r} is not a VAE in the manifest")
            for s in e.sets:
                if s not in target.sets:
                    raise ValueError(f"{e.id} is in set {s!r} but its VAE {vae!r} is not")
        return self

    def __iter__(self) -> Iterator[Entry]:  # type: ignore[override]
        return iter(self.entries)

    def get(self, model_id: str) -> Entry | None:
        return next((e for e in self.entries if e.id == model_id), None)

    def in_set(self, name: str) -> list[Entry]:
        """Entries of a set; ``full`` includes ``default``."""
        wanted = {"default", "full"} if name == "full" else {name}
        return [e for e in self.entries if wanted & set(e.sets)]

    def by_sha256(self, sha256: str) -> Entry | None:
        return next((e for e in self.entries if e.file.sha256 == sha256), None)


class ManifestError(ValueError):
    pass


def find_manifest() -> Path:
    """``$P11_MODEL_MANIFEST``, else the repo's ``models/``, else the data-dir copy."""
    override = os.environ.get("P11_MODEL_MANIFEST")
    if override:
        return Path(override)
    repo = Path(__file__).resolve().parents[3] / "models" / MANIFEST_NAME
    if repo.exists():
        return repo
    return paths.data_dir() / MANIFEST_NAME


def parse_manifest(text: str, path: Path | None = None) -> Manifest:
    where = str(path) if path else "manifest"
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ManifestError(f"{where}: not valid TOML: {exc}") from None
    try:
        return Manifest.model_validate({**data, "path": path})
    except ValidationError as exc:
        raise ManifestError(f"{where}: {exc}") from None


def load_manifest(path: Path | None = None) -> Manifest:
    path = path or find_manifest()
    try:
        text = path.read_text()
    except OSError as exc:
        raise ManifestError(f"cannot read the model manifest {path}: {exc.strerror}") from None
    return parse_manifest(text, path)
