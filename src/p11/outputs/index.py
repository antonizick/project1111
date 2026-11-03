"""SQLite gallery index (spec R7): images, favourites, variation/edit parents, prompt search.

Stdlib ``sqlite3`` with migrations keyed on ``PRAGMA user_version`` and an FTS5 table over the
prompt text. The index is a cache: ``reindex(root)`` rebuilds it from the sidecars. Paths are stored
relative to the outputs root, which is always passed in.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from ..recipe.compile import resolve_bindings
from ..recipe.model import PLACEHOLDER, FileRef, Generate, Inpaint, Recipe, Upscale
from .metadata import MetadataError, RunRecord, read_sidecar


def _v1(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE images (
            id          INTEGER PRIMARY KEY,
            path        TEXT    NOT NULL UNIQUE,
            created_at  TEXT    NOT NULL,
            recipe_id   TEXT    NOT NULL,
            template    TEXT,
            seed        INTEGER NOT NULL,
            model       TEXT,
            width       INTEGER,
            height      INTEGER,
            favourite   INTEGER NOT NULL DEFAULT 0,
            parent_id   INTEGER REFERENCES images(id) ON DELETE SET NULL,
            prompt      TEXT    NOT NULL DEFAULT ''
        );
        CREATE INDEX images_created ON images(created_at DESC);
        CREATE INDEX images_template ON images(template);
        CREATE INDEX images_parent ON images(parent_id);
        CREATE VIRTUAL TABLE images_fts USING fts5(
            prompt, content='images', content_rowid='id', tokenize='unicode61'
        );
        CREATE TRIGGER images_ai AFTER INSERT ON images BEGIN
            INSERT INTO images_fts(rowid, prompt) VALUES (new.id, new.prompt);
        END;
        CREATE TRIGGER images_ad AFTER DELETE ON images BEGIN
            INSERT INTO images_fts(images_fts, rowid, prompt) VALUES ('delete', old.id, old.prompt);
        END;
        CREATE TRIGGER images_au AFTER UPDATE OF prompt ON images BEGIN
            INSERT INTO images_fts(images_fts, rowid, prompt) VALUES ('delete', old.id, old.prompt);
            INSERT INTO images_fts(rowid, prompt) VALUES (new.id, new.prompt);
        END;
        """
    )


#: ``MIGRATIONS[i]`` upgrades the database from ``user_version == i`` to ``i + 1``.
MIGRATIONS: list[Callable[[sqlite3.Connection], None]] = [_v1]
_TOKEN = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class ImageEntry:
    path: str
    created_at: str
    recipe_id: str
    seed: int
    template: str | None = None
    model: str | None = None
    width: int | None = None
    height: int | None = None
    favourite: bool = False
    parent_id: int | None = None
    prompt: str = ""
    id: int | None = None


class GalleryIndex:
    def __init__(self, db_path: Path | str) -> None:
        if isinstance(db_path, Path):
            db_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(db_path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.migrate()

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> GalleryIndex:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def version(self) -> int:
        return int(self.db.execute("PRAGMA user_version").fetchone()[0])

    def migrate(self) -> None:
        current = self.version
        if current > len(MIGRATIONS):
            raise RuntimeError(
                f"The gallery index is from a newer P11 (version {current}); update P11."
            )
        for i in range(current, len(MIGRATIONS)):
            with self.db:
                MIGRATIONS[i](self.db)
                self.db.execute(f"PRAGMA user_version = {i + 1}")

    # -----------------------------------------------------------------------------------------

    def add(self, entry: ImageEntry) -> int:
        with self.db:
            cur = self.db.execute(
                """INSERT INTO images (path, created_at, recipe_id, template, seed, model, width,
                   height, favourite, parent_id, prompt)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(path) DO UPDATE SET created_at = excluded.created_at,
                   recipe_id = excluded.recipe_id, template = excluded.template,
                   seed = excluded.seed, model = excluded.model, width = excluded.width,
                   height = excluded.height, parent_id = excluded.parent_id,
                   prompt = excluded.prompt
                   RETURNING id""",
                (
                    entry.path, entry.created_at, entry.recipe_id, entry.template, entry.seed,
                    entry.model, entry.width, entry.height, int(entry.favourite), entry.parent_id,
                    entry.prompt,
                ),
            )  # fmt: skip
            return int(cur.fetchone()[0])

    def get(self, image_id: int) -> ImageEntry | None:
        row = self.db.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()
        return _entry(row) if row else None

    def by_path(self, path: str) -> ImageEntry | None:
        row = self.db.execute("SELECT * FROM images WHERE path = ?", (path,)).fetchone()
        return _entry(row) if row else None

    def set_favourite(self, image_id: int, favourite: bool = True) -> None:
        with self.db:
            self.db.execute(
                "UPDATE images SET favourite = ? WHERE id = ?", (int(favourite), image_id)
            )

    def delete(self, image_id: int) -> None:
        with self.db:
            self.db.execute("DELETE FROM images WHERE id = ?", (image_id,))

    def children(self, image_id: int) -> list[ImageEntry]:
        rows = self.db.execute(
            "SELECT * FROM images WHERE parent_id = ? ORDER BY created_at, id", (image_id,)
        )
        return [_entry(r) for r in rows]

    def _filters(
        self,
        text: str,
        template: str | None,
        favourites: bool,
        since: str | None,
        until: str | None,
    ) -> tuple[str, list[object]]:
        where: list[str] = []
        args: list[object] = []
        query = fts_query(text)
        if query:
            where.append("id IN (SELECT rowid FROM images_fts WHERE images_fts MATCH ?)")
            args.append(query)
        if template is not None:
            where.append("template = ?")
            args.append(template)
        if favourites:
            where.append("favourite = 1")
        if since is not None:
            where.append("created_at >= ?")
            args.append(since)
        if until is not None:
            where.append("created_at < ?")
            args.append(until)
        return (" WHERE " + " AND ".join(where)) if where else "", args

    def search(
        self,
        text: str = "",
        *,
        template: str | None = None,
        favourites: bool = False,
        since: str | None = None,
        until: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ImageEntry]:
        """Newest first. ``text`` matches prompt words by prefix (``mount`` finds "mountain").

        ``since``/``until`` are ISO timestamps compared with ``created_at`` (``until`` exclusive).
        """
        where, args = self._filters(text, template, favourites, since, until)
        sql = f"SELECT * FROM images{where} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
        args += [max(0, min(limit, 1000)), max(0, offset)]
        return [_entry(r) for r in self.db.execute(sql, args)]

    def search_count(
        self,
        text: str = "",
        *,
        template: str | None = None,
        favourites: bool = False,
        since: str | None = None,
        until: str | None = None,
    ) -> int:
        """How many images ``search`` would page through with the same filters."""
        where, args = self._filters(text, template, favourites, since, until)
        return int(self.db.execute(f"SELECT COUNT(*) FROM images{where}", args).fetchone()[0])

    def count(self) -> int:
        return int(self.db.execute("SELECT COUNT(*) FROM images").fetchone()[0])

    # -----------------------------------------------------------------------------------------

    def reindex(self, root: Path) -> int:
        """Rebuild the index from every sidecar under ``root``; keeps favourites. Returns count."""
        favourites = {
            r["path"] for r in self.db.execute("SELECT path FROM images WHERE favourite = 1")
        }
        records: list[tuple[str, RunRecord]] = []
        for sidecar in sorted(_sidecars(root)):
            try:
                record = read_sidecar(sidecar)
            except (OSError, ValueError, ValidationError, MetadataError):
                continue  # not a P11 sidecar, or unreadable; the image stays out of the index
            rel = _image_rel(root, sidecar)
            if rel is not None:
                records.append((rel, record))
        with self.db:
            self.db.execute("DELETE FROM images")
            self.db.execute("INSERT INTO images_fts(images_fts) VALUES ('rebuild')")
        ids: dict[str, int] = {}
        for rel, record in records:
            ids[rel] = self.add(entry_from_record(rel, record, favourite=rel in favourites))
        with self.db:
            for rel, record in records:
                if record.parent and record.parent in ids:
                    self.db.execute(
                        "UPDATE images SET parent_id = ? WHERE id = ?",
                        (ids[record.parent], ids[rel]),
                    )
        return len(records)


def fts_query(text: str) -> str:
    """User text → a safe FTS5 query: every word must match as a prefix; syntax is ignored."""
    return " ".join(f'"{t}"*' for t in _TOKEN.findall(text.lower()))


def prompt_text(recipe: Recipe, bindings: dict[str, str | FileRef] | None = None) -> str:
    """The searchable prompt text of a recipe, with text slots filled in."""
    values: dict[str, str | FileRef] = {}
    try:
        values = resolve_bindings(recipe, bindings or {})
    except ValueError:
        values = dict(bindings or {})

    def sub(m: re.Match[str]) -> str:
        v = values.get(m.group(1), "")
        return v if isinstance(v, str) else ""

    parts = []
    for step in recipe.steps:
        if isinstance(step, Generate | Inpaint | Upscale) and step.prompt.strip():
            parts.append(PLACEHOLDER.sub(sub, step.prompt).strip())
    return " | ".join(parts)


def entry_from_record(path: str, record: RunRecord, favourite: bool = False) -> ImageEntry:
    out = next((o for o in record.step_outputs if o.path == path), None)
    gen = next((s for s in record.recipe.steps if isinstance(s, Generate)), None)
    model = gen.model.manifest_id if gen and gen.model else None
    if model is None and record.model_hashes:
        model = next(iter(record.model_hashes))
    created = record.created_at
    return ImageEntry(
        path=path,
        created_at=created.isoformat() if isinstance(created, datetime) else str(created),
        recipe_id=record.recipe.id,
        template=record.template,
        seed=record.seed,
        model=model,
        width=out.width if out else None,
        height=out.height if out else None,
        favourite=favourite,
        prompt=prompt_text(record.recipe, record.bindings),
    )


def _sidecars(root: Path) -> Iterator[Path]:
    if root.is_dir():
        yield from (p for p in root.rglob("*.json") if not p.name.startswith("."))


def _image_rel(root: Path, sidecar: Path) -> str | None:
    image = sidecar.with_suffix(".png")
    if not image.exists():
        return None
    return image.relative_to(root).as_posix()


def _entry(row: sqlite3.Row) -> ImageEntry:
    return ImageEntry(
        id=row["id"],
        path=row["path"],
        created_at=row["created_at"],
        recipe_id=row["recipe_id"],
        template=row["template"],
        seed=row["seed"],
        model=row["model"],
        width=row["width"],
        height=row["height"],
        favourite=bool(row["favourite"]),
        parent_id=row["parent_id"],
        prompt=row["prompt"],
    )
