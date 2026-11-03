"""Installed models: the manifest joined with what is on disk, plus user-added models.

``ModelManager`` scans the models root (spec R8), reports each model as ``installed``,
``missing``, ``corrupt`` (size or hash mismatch), ``user-added`` or ``unregistered`` (a file in a
model folder that P11 knows nothing about), installs manifest entries through the verified
downloader, adds user models under the S4 format policy, and resolves model IDs for the recipe
compiler (``p11.recipe.registry.ModelRegistry``).
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal, cast
from urllib.parse import unquote, urlsplit

from p11.recipe.registry import Family, ModelInfo, ModelKind, SamplerDefaults, UnknownModelError

from . import formats
from .download import Downloader, DownloadItem, Progress, human_size
from .manifest import KIND_FOLDERS, Entry, Licence, Manifest, check_filename, load_manifest
from .state import (
    Acknowledgement,
    HashCache,
    LicenceStore,
    ModelState,
    StateStore,
    UserModel,
    now_stamp,
)

State = Literal["installed", "missing", "corrupt", "user-added", "unregistered"]
SETS = ("default", "full", "optional")

#: Sampler defaults for a user-added checkpoint, by family. They are P11's own starting points
#: (the same samplers the curated models use), editable per recipe; not facts about the model.
USER_CHECKPOINT_DEFAULTS: dict[str, SamplerDefaults] = {
    "sdxl": SamplerDefaults("dpmpp_2m", "karras", 30, 5.0, 1, 15),
    "sd15": SamplerDefaults("dpmpp_2m", "karras", 25, 6.0, 1, 12),
}

_SLUG = re.compile(r"[^a-z0-9.-]+")


class ModelError(RuntimeError):
    """A model operation failed; the message is plain English with a hint."""


class LicenceNotAccepted(ModelError):
    def __init__(self, entries: Sequence[Entry]) -> None:
        self.entries = list(entries)
        lines = [f"  - {e.name}: {e.licence.name} ({e.licence.url})" for e in entries]
        super().__init__(
            "These models have licence terms to accept first:\n"
            + "\n".join(lines)
            + "\nRead them, then run again with --accept-licences (or answer yes when asked)."
        )


@dataclass(frozen=True)
class ModelStatus:
    id: str
    name: str
    kind: str
    base: str | None
    state: State
    origin: Literal["manifest", "user", "disk"]
    filename: str
    path: Path | None
    size: int | None
    sha256: str | None
    #: The hash was checked against the file (freshly or from the size+mtime cache).
    verified: bool
    enabled: bool
    sets: tuple[str, ...] = ()
    licence: Licence | None = None
    licence_accepted: bool = False
    format: str = "safetensors"
    detail: str = ""

    def as_json(self) -> dict[str, object]:
        lic = self.licence
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "base": self.base,
            "state": self.state,
            "origin": self.origin,
            "filename": self.filename,
            "path": str(self.path) if self.path else None,
            "size": self.size,
            "sha256": self.sha256,
            "verified": self.verified,
            "enabled": self.enabled,
            "sets": list(self.sets),
            "format": self.format,
            "licence": None
            if lic is None
            else {
                "name": lic.name,
                "url": lic.url,
                "commercial_use": lic.commercial_use,
                "flags": list(lic.flags),
                "accepted": self.licence_accepted,
            },
            "detail": self.detail,
        }


@dataclass
class InstallReport:
    downloaded: list[str] = field(default_factory=list)
    copied: list[str] = field(default_factory=list)
    present: list[str] = field(default_factory=list)
    repaired: list[str] = field(default_factory=list)
    accepted: list[str] = field(default_factory=list)
    bytes_downloaded: int = 0

    def as_json(self) -> dict[str, object]:
        return {
            "downloaded": self.downloaded,
            "copied": self.copied,
            "present": self.present,
            "repaired": self.repaired,
            "licences_accepted": self.accepted,
            "bytes_downloaded": self.bytes_downloaded,
        }


@dataclass(frozen=True)
class InstallPlan:
    entries: tuple[Entry, ...]
    #: Entries whose file is absent, incomplete or wrong.
    to_fetch: tuple[Entry, ...]
    #: Entries whose licence needs an acknowledgement that is not recorded yet.
    to_accept: tuple[Entry, ...]
    download_bytes: int


class ModelManager:
    def __init__(
        self,
        root: Path,
        manifest: Manifest | None = None,
        *,
        state: StateStore | None = None,
        licences: LicenceStore | None = None,
        hashes: HashCache | None = None,
    ) -> None:
        self.root = root
        self.manifest = manifest or load_manifest()
        self.state = state or StateStore()
        self.licences = licences or LicenceStore()
        self.hashes = hashes or HashCache()

    @classmethod
    def from_settings(cls) -> ModelManager:
        from p11.config import load_settings

        return cls(load_settings().models_root)

    # -- layout --------------------------------------------------------------------------------

    def folder(self, kind: str) -> Path:
        return self.root / KIND_FOLDERS[kind]

    def path_of(self, entry: Entry) -> Path:
        return self.folder(entry.kind) / entry.file.filename

    def ensure_folders(self) -> None:
        for sub in KIND_FOLDERS.values():
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    # -- status --------------------------------------------------------------------------------

    def _entry_status(self, entry: Entry, st: ModelState, *, verify: bool) -> ModelStatus:
        base = ModelStatus(
            id=entry.id,
            name=entry.name,
            kind=entry.kind,
            base=entry.base,
            state="missing",
            origin="manifest",
            filename=entry.file.filename,
            path=None,
            size=None,
            sha256=entry.file.sha256,
            verified=False,
            enabled=entry.id not in st.disabled,
            sets=entry.sets,
            licence=entry.licence,
            licence_accepted=self.licences.accepted(entry.id, entry.licence.name),
        )
        path = self.path_of(entry)
        if not path.is_file():
            alt = self._find_by_hash(entry, verify=verify)
            if alt is None:
                return base
            path = alt
        size = path.stat().st_size
        found = replace(base, path=path, filename=path.name, size=size)
        if size != entry.file.size:
            return replace(
                found, state="corrupt", detail=f"size {size} bytes, expected {entry.file.size}"
            )
        digest = self.hashes.sha256(path, fresh=verify)
        if digest != entry.file.sha256:
            return replace(
                found,
                state="corrupt",
                verified=True,
                detail=f"SHA-256 {digest[:12]}… does not match the manifest",
            )
        return replace(found, state="installed", verified=True)

    def _find_by_hash(self, entry: Entry, *, verify: bool) -> Path | None:
        """Join by hash: the entry's file under another name in its folder (e.g. a manual copy)."""
        known = self._known_files()
        folder = self.folder(entry.kind)
        if not folder.is_dir():
            return None
        for p in sorted(folder.iterdir()):
            if not p.is_file() or p in known or p.name.endswith(".part"):
                continue
            if p.stat().st_size == entry.file.size and (
                self.hashes.sha256(p, fresh=verify) == entry.file.sha256
            ):
                return p
        return None

    def _known_files(self) -> set[Path]:
        st = self.state.load()
        files = {self.path_of(e) for e in self.manifest}
        files |= {self.folder(u.kind) / u.filename for u in st.user.values()}
        return files

    def _user_status(self, user: UserModel, st: ModelState, *, verify: bool) -> ModelStatus:
        path = self.folder(user.kind) / user.filename
        base = ModelStatus(
            id=user.id,
            name=user.filename,
            kind=user.kind,
            base=user.base,
            state="missing",
            origin="user",
            filename=user.filename,
            path=None,
            size=None,
            sha256=user.sha256,
            verified=False,
            enabled=user.id not in st.disabled,
            format=user.format,
            detail="the file was moved or deleted",
        )
        if not path.exists():
            return base
        found = replace(base, path=path, size=path.stat().st_size, verified=True, detail="")
        if self.hashes.sha256(path, fresh=verify) != user.sha256:
            return replace(found, state="corrupt", detail="the file changed since it was added")
        return replace(found, state="user-added")

    def statuses(
        self, *, verify: bool = False, include_unregistered: bool = True
    ) -> list[ModelStatus]:
        st = self.state.load()
        out = [self._entry_status(e, st, verify=verify) for e in self.manifest]
        out += [self._user_status(u, st, verify=verify) for u in st.user.values()]
        if include_unregistered:
            claimed = {s.path for s in out if s.path}
            for kind, sub in KIND_FOLDERS.items():
                folder = self.root / sub
                if not folder.is_dir():
                    continue
                for p in sorted(folder.iterdir()):
                    if p.is_file() and p not in claimed and not p.name.startswith("."):
                        if p.name.endswith(".part"):
                            continue
                        out.append(
                            ModelStatus(
                                id=_slug(p.stem),
                                name=p.name,
                                kind=kind,
                                base=None,
                                state="unregistered",
                                origin="disk",
                                filename=p.name,
                                path=p,
                                size=p.stat().st_size,
                                sha256=None,
                                verified=False,
                                enabled=False,
                                format="unknown",
                                detail=f"not known to P11; register it with `p11 models add {p}`",
                            )
                        )
        return out

    def status(self, model_id: str, *, verify: bool = False) -> ModelStatus:
        st = self.state.load()
        entry = self.manifest.get(model_id)
        if entry:
            return self._entry_status(entry, st, verify=verify)
        if model_id in st.user:
            return self._user_status(st.user[model_id], st, verify=verify)
        raise ModelError(f"No model {model_id!r}. `p11 models list` shows what P11 knows.")

    # -- install -------------------------------------------------------------------------------

    def resolve_target(self, target: str) -> list[Entry]:
        """A set name or a manifest ID, plus the VAEs those checkpoints default to."""
        if target in SETS:
            entries = self.manifest.in_set(target)
        else:
            entry = self.manifest.get(target)
            if entry is None:
                raise ModelError(
                    f"{target!r} is neither a set ({', '.join(SETS)}) nor a manifest model ID."
                )
            entries = [entry]
        out: list[Entry] = []
        for e in entries:
            vae = e.defaults.vae if e.defaults else None
            for dep in [e, self.manifest.get(vae) if vae else None]:
                if dep is not None and dep not in out:
                    out.append(dep)
        return out

    def plan(self, target: str) -> InstallPlan:
        entries = self.resolve_target(target)
        st = self.state.load()
        fetch = [e for e in entries if self._entry_status(e, st, verify=False).state != "installed"]
        accept = [
            e
            for e in entries
            if e.licence.needs_acknowledgement and not self.licences.accepted(e.id, e.licence.name)
        ]
        remaining = sum(
            Downloader.remaining(self._item(e)) if not self.path_of(e).exists() else e.size
            for e in fetch
        )
        return InstallPlan(tuple(entries), tuple(fetch), tuple(accept), remaining)

    def _item(self, entry: Entry) -> DownloadItem:
        f = entry.file
        return DownloadItem(f.url, self.path_of(entry), f.sha256, f.size, label=entry.id)

    def install(
        self,
        target: str,
        *,
        downloader: Downloader,
        accept_licences: bool = False,
        confirm: Callable[[Entry], bool] | None = None,
        progress: Progress | None = None,
        source_dirs: Iterable[Path] = (),
    ) -> InstallReport:
        plan = self.plan(target)
        report = InstallReport()
        self._acknowledge(plan.to_accept, accept_licences, confirm, report)
        self.ensure_folders()
        downloads: list[tuple[Entry, DownloadItem]] = []
        st = self.state.load()
        for entry in plan.entries:
            status = self._entry_status(entry, st, verify=False)
            if status.state == "installed":
                report.present.append(entry.id)
                continue
            if status.state == "corrupt" and status.path is not None:
                # A P11-managed file with the wrong bytes: replace it (a .part is kept for resume).
                status.path.unlink()
                self.hashes.forget(status.path)
                report.repaired.append(entry.id)
            if self._copy_from_sources(entry, source_dirs):
                report.copied.append(entry.id)
                continue
            downloads.append((entry, self._item(entry)))
        downloader.check_space([item for _, item in downloads])
        for entry, item in downloads:
            before = Downloader.remaining(item)
            path = downloader.fetch(item, progress, check_space=False)
            self.hashes.remember(path, entry.file.sha256)
            report.downloaded.append(entry.id)
            report.bytes_downloaded += before
        return report

    def _acknowledge(
        self,
        entries: Sequence[Entry],
        accept_all: bool,
        confirm: Callable[[Entry], bool] | None,
        report: InstallReport,
    ) -> None:
        if not entries:
            return
        how = "--accept-licences" if accept_all else "interactive"
        if not accept_all:
            if confirm is None:
                raise LicenceNotAccepted(entries)
            refused = [e for e in entries if not confirm(e)]
            if refused:
                raise LicenceNotAccepted(refused)
        stamp = now_stamp()
        self.licences.record(
            [
                Acknowledgement(
                    e.id, e.licence.name, e.licence.url, e.licence.commercial_use, stamp, how
                )
                for e in entries
            ]
        )
        report.accepted.extend(e.id for e in entries)

    def _copy_from_sources(self, entry: Entry, source_dirs: Iterable[Path]) -> bool:
        """Reuse an already-downloaded copy (H1): hard link when possible, else copy; verified."""
        for src_root in source_dirs:
            for candidate in (
                src_root / entry.folder / entry.file.filename,
                src_root / entry.file.filename,
            ):
                if not candidate.is_file() or candidate.stat().st_size != entry.file.size:
                    continue
                if self.hashes.sha256(candidate) != entry.file.sha256:
                    continue
                dest = self.path_of(entry)
                tmp = dest.with_name(dest.name + ".part")
                tmp.unlink(missing_ok=True)
                try:
                    os.link(candidate, tmp)
                except OSError:
                    shutil.copyfile(candidate, tmp)
                os.replace(tmp, dest)
                self.hashes.remember(dest, entry.file.sha256)
                return True
        return False

    # -- verify, enable, remove ------------------------------------------------------------------

    def verify(self, model_ids: Sequence[str] = ()) -> list[ModelStatus]:
        """Re-hash files from disk, ignoring the cache."""
        if model_ids:
            return [self.status(i, verify=True) for i in model_ids]
        return [
            s
            for s in self.statuses(verify=True, include_unregistered=False)
            if s.state != "missing" or s.origin == "user"
        ]

    def set_enabled(self, model_id: str, enabled: bool) -> None:
        self.status(model_id)  # raises for an unknown ID
        st = self.state.load()
        disabled = set(st.disabled)
        if enabled:
            disabled.discard(model_id)
        else:
            disabled.add(model_id)
        st.disabled = sorted(disabled)
        self.state.save(st)

    def remove(self, model_id: str, *, delete_file: bool = False) -> str:
        """Delete a manifest model's file, or unregister a user model (its file only on request)."""
        st = self.state.load()
        if model_id in st.user:
            user = st.user.pop(model_id)
            path = self.folder(user.kind) / user.filename
            st.disabled = [d for d in st.disabled if d != model_id]
            self.state.save(st)
            if delete_file and (path.exists() or path.is_symlink()):
                path.unlink()
                self.hashes.forget(path)
                return f"Removed {model_id} and deleted {path}."
            return f"Removed {model_id} from P11; the file {path} was left in place."
        entry = self.manifest.get(model_id)
        if entry is None:
            raise ModelError(f"No model {model_id!r}. `p11 models list` shows what P11 knows.")
        path = self.path_of(entry)
        if not path.exists():
            return f"{model_id} is not installed."
        self.hashes.forget(path)
        path.unlink()
        return (
            f"Deleted {path} ({human_size(entry.file.size)}). "
            f"`p11 models install {model_id}` brings it back."
        )

    # -- user-added models (S4) ------------------------------------------------------------------

    def add(
        self,
        source: str,
        *,
        kind: str | None = None,
        model_id: str | None = None,
        allow_pickle: bool = False,
        link: bool = False,
        downloader: Downloader | None = None,
        warn: Callable[[str], None] = lambda msg: print(msg, file=sys.stderr),
    ) -> ModelStatus:
        if kind is not None and kind not in KIND_FOLDERS:
            raise ModelError(f"Unknown kind {kind!r}; one of {', '.join(KIND_FOLDERS)}.")
        is_url = urlsplit(source).scheme in ("http", "https")
        if is_url:
            if link:
                raise ModelError("--link only works for local files.")
            if downloader is None:
                raise ModelError("a downloader is needed to add a URL")
            name = check_filename(unquote(Path(urlsplit(source).path).name))
            staging = self.root / ".incoming"
            staging.mkdir(parents=True, exist_ok=True)
            src = downloader.fetch(DownloadItem(source, staging / name, None, None))
        else:
            src = Path(source).expanduser().resolve()
            if not src.is_file():
                raise ModelError(f"{src} is not a file.")
            name = check_filename(src.name)

        try:
            fmt = formats.sniff(src)
            if fmt in formats.PICKLE_FORMATS:
                if not allow_pickle:
                    raise ModelError(
                        f"{name} is a pickle-based file ({fmt}), which P11 refuses by default. "
                        f"{formats.PICKLE_RISK} To add it anyway: --allow-pickle."
                    )
                warn(f"Warning: {formats.PICKLE_RISK}")
            elif fmt not in formats.SAFE_FORMATS:
                raise ModelError(
                    f"{name} is not a safetensors or GGUF file (format not recognised from its "
                    "content). P11 only adds model files it can identify."
                )
            guessed_kind, base = (None, None)
            if fmt == "safetensors":
                guessed_kind, base = formats.detect(formats.read_safetensors_header(src))
            kind = kind or guessed_kind
            if kind is None:
                raise ModelError(
                    f"Could not tell what kind of model {name} is; pass --kind "
                    f"({', '.join(KIND_FOLDERS)})."
                )
            digest = self.hashes.sha256(src, fresh=True)
            entry = self.manifest.by_sha256(digest)
            if entry is not None:
                # Join by hash: this is a curated model; install it under its manifest name.
                self._place(src, self.path_of(entry), move=is_url, link=link)
                self.hashes.remember(self.path_of(entry), digest)
                return self.status(entry.id)

            st = self.state.load()
            mid = model_id or _slug(Path(name).stem)
            if self.manifest.get(mid) is not None or mid in st.user:
                raise ModelError(f"A model with ID {mid!r} already exists; pass --id.")
            dest = self.folder(kind) / name
            if dest.exists() or dest.is_symlink():
                raise ModelError(f"{dest} already exists.")
            self._place(src, dest, move=is_url, link=link)
            self.hashes.remember(dest, digest)
            st.user[mid] = UserModel(
                id=mid,
                kind=kind,
                filename=name,
                sha256=digest,
                size=dest.stat().st_size,
                format=fmt,
                base=base,
                source=source if is_url else str(src),
                added_at=now_stamp(),
                copied=not link,
                pickle_allowed=fmt in formats.PICKLE_FORMATS,
            )
            self.state.save(st)
            return self.status(mid)
        finally:
            if is_url and src.exists():
                src.unlink()

    @staticmethod
    def _place(src: Path, dest: Path, *, move: bool, link: bool) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if link:
            dest.symlink_to(src)
        elif move:
            os.replace(src, dest)
        else:
            tmp = dest.with_name(dest.name + ".part")
            shutil.copyfile(src, tmp)
            os.replace(tmp, dest)

    # -- compiler registry ---------------------------------------------------------------------

    def registry(self, *, require_installed: bool = True) -> ManagerRegistry:
        return ManagerRegistry(self, require_installed=require_installed)

    def info(self, model_id: str, *, require_installed: bool = True) -> ModelInfo:
        st = self.state.load()
        if model_id in st.disabled:
            raise UnknownModelError(
                f"Model {model_id!r} is disabled. Enable it with `p11 models enable {model_id}`."
            )
        entry = self.manifest.get(model_id)
        if entry is not None:
            filename = entry.file.filename
            if require_installed:
                status = self._entry_status(entry, st, verify=False)
                if status.state != "installed":
                    raise UnknownModelError(
                        f"Model {model_id!r} is {status.state}. "
                        f"Run `p11 models install {model_id}`."
                    )
                filename = status.filename
            return entry_info(entry, filename)
        user = st.user.get(model_id)
        if user is None:
            raise UnknownModelError(f"Model {model_id!r} is not installed or not in the manifest.")
        if user.format in formats.PICKLE_FORMATS and not user.pickle_allowed:
            raise UnknownModelError(f"Model {model_id!r} is a pickle file that was not allowed.")
        if require_installed and self._user_status(user, st, verify=False).state != "user-added":
            raise UnknownModelError(f"Model {model_id!r}: its file is missing or changed.")
        family = cast(Family, user.base) if user.base in ("sdxl", "sd15") else None
        defaults = (
            USER_CHECKPOINT_DEFAULTS.get(user.base or "") if user.kind == "checkpoint" else None
        )
        return ModelInfo(
            manifest_id=user.id,
            kind=cast(ModelKind, user.kind),
            filename=user.filename,
            sha256=user.sha256,
            family=family,
            defaults=defaults,
        )

    # -- engine config -------------------------------------------------------------------------

    def write_extra_model_paths(self, engine_dir: Path, template: Path | None = None) -> bool:
        """Render ``extra_model_paths.yaml`` (same template as ``scripts/engine_setup.sh``).

        Returns ``True`` when the file changed.
        """
        template = template or Path(__file__).resolve().parents[3] / "engine" / (
            "extra_model_paths.yaml.tmpl"
        )
        text = template.read_text().replace("@MODELS@", str(self.root))
        target = engine_dir / "extra_model_paths.yaml"
        if target.exists() and target.read_text() == text:
            return False
        engine_dir.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".new")
        tmp.write_text(text)
        os.replace(tmp, target)
        return True


def entry_info(entry: Entry, filename: str | None = None) -> ModelInfo:
    """The compiler's view of a manifest entry."""
    d = entry.defaults
    family: Family | None = entry.base if entry.base != "any" else None
    return ModelInfo(
        manifest_id=entry.id,
        kind=cast(ModelKind, entry.kind),
        filename=filename or entry.file.filename,
        sha256=entry.file.sha256,
        family=family,
        defaults=None
        if d is None
        else SamplerDefaults(d.sampler, d.scheduler, d.steps, d.cfg, d.clip_skip, d.hires_steps),
        vae=d.vae if d else None,
        scale=entry.scale,
    )


class ManagerRegistry:
    """``p11.recipe.registry.ModelRegistry`` over the model manager (the app's registry)."""

    def __init__(self, manager: ModelManager, *, require_installed: bool = True) -> None:
        self._manager = manager
        self._require_installed = require_installed

    def get(self, manifest_id: str) -> ModelInfo:
        return self._manager.info(manifest_id, require_installed=self._require_installed)


def _slug(text: str) -> str:
    slug = _SLUG.sub("-", text.lower()).strip("-.")
    return (slug or "model")[:64]
