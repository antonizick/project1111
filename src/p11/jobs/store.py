"""Persistent job table (SQLite), so a Studio restart shows which jobs were interrupted.

Recipes and bindings are stored because the job must be re-runnable and inspectable; the file
lives in the private data dir (``0700``) like the gallery index. Prompt text is never logged.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

JobState = Literal["queued", "running", "paused", "cancelled", "failed", "done"]
#: A job is a recipe run (the default) or a video face-swap pipeline run (Phase 13).
JobKind = Literal["recipe", "video"]
ACTIVE: frozenset[str] = frozenset({"queued", "running", "paused"})
FINISHED: frozenset[str] = frozenset({"cancelled", "failed", "done"})

INTERRUPTED_CODE = "job.interrupted"
INTERRUPTED_MESSAGE = "P11 Studio stopped while this job was waiting or running."
INTERRUPTED_HINT = "Run it again; nothing was lost except this job's unfinished images."


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class JobError:
    code: str
    message: str
    hint: str = ""

    def as_json(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "hint": self.hint}


@dataclass(frozen=True)
class Job:
    id: str
    state: JobState
    recipe: dict[str, Any]
    bindings: dict[str, Any]
    count: int = 1
    template: str | None = None
    parent: str | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    #: Gallery image IDs produced so far.
    images: tuple[int, ...] = ()
    #: 0..1 over the whole job.
    progress: float = 0.0
    error: JobError | None = None
    #: Note shown while ``paused`` (thermal) or after an OOM retry.
    note: str | None = None
    kind: JobKind = "recipe"
    #: Video face-swap settings (``kind="video"``); ``None`` for a recipe run.
    spec: dict[str, Any] | None = None

    def summary(self) -> dict[str, Any]:
        """The job as the API shows it (recipe, bindings and spec stay out: they can be private)."""
        return {
            "id": self.id,
            "state": self.state,
            "kind": self.kind,
            "name": "Video face-swap" if self.kind == "video" else str(self.recipe.get("name", "")),
            "count": self.count,
            "template": self.template,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "images": list(self.images),
            "progress": round(self.progress, 4),
            "error": self.error.as_json() if self.error else None,
            "note": self.note,
        }


def _v1(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE jobs (
            id          TEXT PRIMARY KEY,
            state       TEXT NOT NULL,
            recipe      TEXT NOT NULL,
            bindings    TEXT NOT NULL,
            count       INTEGER NOT NULL DEFAULT 1,
            template    TEXT,
            parent      TEXT,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            images      TEXT NOT NULL DEFAULT '[]',
            progress    REAL NOT NULL DEFAULT 0,
            error       TEXT,
            note        TEXT
        );
        CREATE INDEX jobs_created ON jobs(created_at DESC);
        CREATE INDEX jobs_state ON jobs(state);
        """
    )


def _v2(db: sqlite3.Connection) -> None:
    """Phase 13: video face-swap jobs carry a kind and their own spec instead of a recipe."""
    db.execute("ALTER TABLE jobs ADD COLUMN kind TEXT NOT NULL DEFAULT 'recipe'")
    db.execute("ALTER TABLE jobs ADD COLUMN spec TEXT")


MIGRATIONS: list[Callable[[sqlite3.Connection], None]] = [_v1, _v2]


class JobStore:
    def __init__(self, db_path: Path | str) -> None:
        if isinstance(db_path, Path):
            db_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(db_path))
        self.db.row_factory = sqlite3.Row
        version = int(self.db.execute("PRAGMA user_version").fetchone()[0])
        for i in range(version, len(MIGRATIONS)):
            with self.db:
                MIGRATIONS[i](self.db)
                self.db.execute(f"PRAGMA user_version = {i + 1}")
        if isinstance(db_path, Path):
            db_path.chmod(0o600)

    def close(self) -> None:
        self.db.close()

    def put(self, job: Job) -> Job:
        job = replace(job, updated_at=_now())
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO jobs "
                "(id, state, recipe, bindings, count, template, parent, created_at, updated_at, "
                " images, progress, error, note, kind, spec) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    job.id,
                    job.state,
                    json.dumps(job.recipe),
                    json.dumps(job.bindings),
                    job.count,
                    job.template,
                    job.parent,
                    job.created_at,
                    job.updated_at,
                    json.dumps(list(job.images)),
                    job.progress,
                    json.dumps(job.error.as_json()) if job.error else None,
                    job.note,
                    job.kind,
                    json.dumps(job.spec) if job.spec is not None else None,
                ),
            )
        return job

    def get(self, job_id: str) -> Job | None:
        row = self.db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _job(row) if row else None

    def recent(self, limit: int = 50, states: frozenset[str] | None = None) -> list[Job]:
        sql = "SELECT * FROM jobs"
        args: list[object] = []
        if states:
            sql += f" WHERE state IN ({','.join('?' * len(states))})"
            args += sorted(states)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(max(1, min(limit, 500)))
        return [_job(r) for r in self.db.execute(sql, args)]

    def mark_interrupted(self) -> list[str]:
        """On startup: every job still queued, running or paused failed when the Studio stopped."""
        ids = [r["id"] for r in self.db.execute("SELECT id FROM jobs WHERE state IN (?,?,?)",
                                                sorted(ACTIVE))]  # fmt: skip
        error = json.dumps(JobError(INTERRUPTED_CODE, INTERRUPTED_MESSAGE, INTERRUPTED_HINT)
                           .as_json())  # fmt: skip
        with self.db:
            self.db.executemany(
                "UPDATE jobs SET state = 'failed', error = ?, updated_at = ? WHERE id = ?",
                [(error, _now(), i) for i in ids],
            )
        return ids


def _job(row: sqlite3.Row) -> Job:
    err = json.loads(row["error"]) if row["error"] else None
    return Job(
        id=row["id"],
        state=row["state"],
        recipe=json.loads(row["recipe"]),
        bindings=json.loads(row["bindings"]),
        count=row["count"],
        template=row["template"],
        parent=row["parent"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        images=tuple(json.loads(row["images"])),
        progress=row["progress"],
        error=JobError(**err) if err else None,
        note=row["note"],
        kind=row["kind"],
        spec=json.loads(row["spec"]) if row["spec"] else None,
    )
