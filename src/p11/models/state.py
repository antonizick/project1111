"""Small on-disk stores of the model manager.

- ``~/.config/p11/licences.toml``: licence acknowledgements with a timestamp (Task 4).
- ``~/.config/p11/models.toml``: enabled/disabled flags and user-added models. Kept apart from
  ``config.toml`` so P11 never rewrites the file the user edits by hand.
- ``~/.cache/p11/model-hashes.json``: SHA-256 per file keyed by size and mtime, so ``list`` and a
  second ``install`` do not re-hash 7 GB checkpoints. ``verify`` ignores it.

The stores are tiny and written atomically (temp file + rename).
"""

from __future__ import annotations

import json
import os
import tempfile
import tomllib
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from p11 import paths

from .download import sha256_file


def now_stamp() -> str:
    """``YYYY-MM-DD HH:MM TZ`` in local time, the project's timestamp format."""
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")


def _atomic_write(path: Path, text: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        # JSON string escapes are valid TOML basic-string escapes.
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list | tuple):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    raise TypeError(f"cannot write {type(value).__name__} to TOML")


def dump_toml(data: Mapping[str, Any], header: str = "") -> str:
    """Top-level scalars, then ``[table."key"]`` sub-tables of scalars (all this module needs)."""
    lines = [f"# {line}" for line in header.splitlines()]
    for key, value in data.items():
        if not isinstance(value, Mapping):
            lines.append(f"{json.dumps(key)} = {_toml_value(value)}")
    for key, table in data.items():
        if not isinstance(table, Mapping):
            continue
        for name, row in table.items():
            lines.append("")
            lines.append(f"[{json.dumps(key)}.{json.dumps(name)}]")
            for k, v in row.items():
                if v is not None:
                    lines.append(f"{json.dumps(k)} = {_toml_value(v)}")
    return "\n".join(lines).lstrip("\n") + "\n"


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text())
    except FileNotFoundError:
        return {}


# -- licences --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Acknowledgement:
    model_id: str
    licence: str
    url: str
    commercial_use: bool
    accepted_at: str
    how: str


class LicenceStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or paths.config_dir() / "licences.toml"

    def all(self) -> dict[str, Acknowledgement]:
        rows = _load_toml(self.path).get("accepted", {})
        return {k: Acknowledgement(model_id=k, **v) for k, v in rows.items()}

    def accepted(self, model_id: str, licence: str) -> bool:
        ack = self.all().get(model_id)
        return ack is not None and ack.licence == licence

    def record(self, acks: list[Acknowledgement]) -> None:
        current = self.all()
        for a in acks:
            current[a.model_id] = a
        rows = {
            k: {kk: vv for kk, vv in asdict(v).items() if kk != "model_id"}
            for k, v in sorted(current.items())
        }
        _atomic_write(
            self.path,
            dump_toml(
                {"accepted": rows},
                header="Model licence acknowledgements, written by `p11 models install`.\n"
                "Delete an entry to be asked again.",
            ),
        )


# -- enabled flags and user-added models -----------------------------------------------------


@dataclass
class UserModel:
    id: str
    kind: str
    filename: str
    sha256: str
    size: int
    format: str
    base: str | None = None
    source: str = ""
    added_at: str = ""
    #: P11 copied (or downloaded) the file into the models folder; a link otherwise.
    copied: bool = True
    pickle_allowed: bool = False


@dataclass
class ModelState:
    disabled: list[str] = field(default_factory=list)
    user: dict[str, UserModel] = field(default_factory=dict)


class StateStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or paths.config_dir() / "models.toml"

    def load(self) -> ModelState:
        data = _load_toml(self.path)
        users = {k: UserModel(id=k, **v) for k, v in data.get("user", {}).items()}
        return ModelState(disabled=list(data.get("disabled", [])), user=users)

    def save(self, state: ModelState) -> None:
        user = {
            k: {kk: vv for kk, vv in asdict(v).items() if kk != "id"}
            for k, v in sorted(state.user.items())
        }
        _atomic_write(
            self.path,
            dump_toml(
                {"disabled": sorted(set(state.disabled)), "user": user},
                header="P11 model state, written by `p11 models`. Edit with the CLI.",
            ),
        )


# -- hash cache ------------------------------------------------------------------------------


class HashCache:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or paths.cache_dir() / "model-hashes.json"
        self._data: dict[str, list[Any]] | None = None

    def _load(self) -> dict[str, list[Any]]:
        if self._data is None:
            try:
                raw = json.loads(self.path.read_text())
                self._data = raw if isinstance(raw, dict) else {}
            except (FileNotFoundError, json.JSONDecodeError):
                self._data = {}
        return self._data

    @staticmethod
    def _key(path: Path) -> tuple[str, int, int]:
        st = path.stat()
        return str(path.resolve()), st.st_size, st.st_mtime_ns

    def cached(self, path: Path) -> str | None:
        key, size, mtime = self._key(path)
        row = self._load().get(key)
        if row and row[0] == size and row[1] == mtime:
            return str(row[2])
        return None

    def remember(self, path: Path, digest: str) -> None:
        key, size, mtime = self._key(path)
        self._load()[key] = [size, mtime, digest]
        _atomic_write(self.path, json.dumps(self._data, indent=0, sort_keys=True), 0o644)

    def forget(self, path: Path) -> None:
        data = self._load()
        if data.pop(str(path.resolve()), None) is not None:
            _atomic_write(self.path, json.dumps(data, indent=0, sort_keys=True), 0o644)

    def sha256(self, path: Path, *, fresh: bool = False) -> str:
        if not fresh:
            hit = self.cached(path)
            if hit:
                return hit
        digest = sha256_file(path)
        self.remember(path, digest)
        return digest
