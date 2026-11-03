"""``p11 models``: list, install, verify, add, remove, enable, disable, licences.

Every command takes ``--json`` for the installer (Phase 15) and the Models page (Phase 14): the
result goes to stdout as one JSON document, progress and warnings go to stderr.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import typer

from p11 import paths

from .download import Downloader, DownloadError, SecretsError, human_size, load_tokens
from .formats import FormatError
from .manifest import KIND_FOLDERS, Entry, ManifestError
from .registry import SETS, ModelError, ModelManager, ModelStatus

app = typer.Typer(help="Manage models: the curated set and your own.", no_args_is_help=True)

JSON_OPT = typer.Option(False, "--json", help="Print the result as JSON.")
FROM_OPT = typer.Option(
    [],
    "--from",
    help="A directory with already-downloaded files to hard-link or copy (verified by hash).",
)
IDS_ARG = typer.Argument(None, help="Model IDs (default: every installed model).")


def _manager() -> ModelManager:
    return ModelManager.from_settings()


def _emit(as_json: bool, data: Any, text: str) -> None:
    if as_json:
        typer.echo(json.dumps(data, indent=2, sort_keys=True))
    elif text:
        typer.echo(text)


@contextmanager
def _errors(as_json: bool) -> Iterator[None]:
    try:
        yield
    except (ModelError, DownloadError, ManifestError, SecretsError, FormatError) as exc:
        if as_json:
            typer.echo(json.dumps({"error": str(exc)}))
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None


def _flag(status: ModelStatus) -> str:
    lic = status.licence
    if lic is None:
        return ""
    return "commercial ok" if lic.commercial_use else "NON-COMMERCIAL"


def _table(rows: list[ModelStatus]) -> str:
    if not rows:
        return "No models."
    lines = [f"{'ID':30} {'KIND':10} {'STATE':12} {'SIZE':>9}  {'SETS':12} LICENCE"]
    for s in rows:
        state = s.state if s.enabled or s.state == "unregistered" else f"{s.state}*"
        size = human_size(s.size) if s.size else "-"
        lic = f"{s.licence.name} ({_flag(s)})" if s.licence else "-"
        lines.append(
            f"{s.id[:30]:30} {s.kind:10} {state:12} {size:>9}  {','.join(s.sets) or '-':12} {lic}"
        )
    if any(not s.enabled and s.state != "unregistered" for s in rows):
        lines.append("* disabled")
    return "\n".join(lines)


@app.command("list")
def list_models(
    set_name: str | None = typer.Option(
        None, "--set", help="Only this set (default|full|optional)."
    ),
    as_json: bool = JSON_OPT,
) -> None:
    """Show every model P11 knows and its state (installed, missing, corrupt, user-added)."""
    with _errors(as_json):
        m = _manager()
        rows = m.statuses()
        if set_name:
            wanted = {e.id for e in m.manifest.in_set(set_name)}
            rows = [s for s in rows if s.id in wanted]
        _emit(
            as_json,
            {"models_root": str(m.root), "models": [s.as_json() for s in rows]},
            f"Models root: {m.root}\n{_table(rows)}",
        )


def _progress() -> Callable[[str, int, int], None]:
    shown: dict[str, int] = {}

    def report(label: str, done: int, total: int) -> None:
        pct = done * 100 // total if total else 0
        step = pct // 10
        if shown.get(label) != step:
            shown[label] = step
            typer.echo(f"  {label}: {pct:3d} % of {human_size(total)}", err=True)

    return report


def _confirm(entry: Entry) -> bool:
    lic = entry.licence
    flags = ", ".join(lic.flags) or "none"
    typer.echo(
        f"\n{entry.name} is under {lic.name}: {lic.url}\n"
        f"  commercial use allowed: {'yes' if lic.commercial_use else 'NO'}; terms: {flags}",
        err=True,
    )
    return typer.confirm("Accept this licence?", default=False, err=True)


@app.command()
def install(
    target: str = typer.Argument(..., help=f"A set ({'|'.join(SETS)}) or a model ID."),
    accept_licences: bool = typer.Option(
        False, "--accept-licences", help="Accept the licences of these models without asking."
    ),
    source: list[Path] = FROM_OPT,
    dry_run: bool = typer.Option(False, "--dry-run", help="Only show what would be downloaded."),
    as_json: bool = JSON_OPT,
) -> None:
    """Download, verify and register a set or one model. Safe to re-run: it resumes."""
    with _errors(as_json):
        m = _manager()
        plan = m.plan(target)
        total = sum(e.size for e in plan.entries)
        typer.echo(
            f"{target}: {len(plan.entries)} model(s), {human_size(total)} in total; "
            f"{len(plan.to_fetch)} to fetch, up to {human_size(plan.download_bytes)} to download.",
            err=True,
        )
        if dry_run:
            _emit(
                as_json,
                {
                    "models": [e.id for e in plan.entries],
                    "to_fetch": [e.id for e in plan.to_fetch],
                    "licences_to_accept": [e.id for e in plan.to_accept],
                    "total_bytes": total,
                    "download_bytes": plan.download_bytes,
                },
                "",
            )
            return
        confirm = _confirm if sys.stdin.isatty() and not accept_licences else None
        with Downloader(tokens=load_tokens()) as dl:
            report = m.install(
                target,
                downloader=dl,
                accept_licences=accept_licences,
                confirm=confirm,
                progress=None if as_json else _progress(),
                source_dirs=source,
            )
        engine = paths.resolve().engine
        if engine.is_dir() and m.write_extra_model_paths(engine):
            typer.echo(f"Updated {engine / 'extra_model_paths.yaml'}", err=True)
        _emit(
            as_json,
            report.as_json(),
            f"Done: {len(report.downloaded)} downloaded ({human_size(report.bytes_downloaded)}), "
            f"{len(report.copied)} copied, {len(report.present)} already present"
            + (f", {len(report.repaired)} repaired" if report.repaired else "")
            + ".",
        )


@app.command()
def verify(
    ids: list[str] | None = IDS_ARG,
    as_json: bool = JSON_OPT,
) -> None:
    """Re-hash model files from disk and report any that are damaged. Exit 1 if any is."""
    with _errors(as_json):
        rows = _manager().verify(ids or [])
        bad = [s for s in rows if s.state in ("corrupt", "missing")]
        lines = [
            f"{'OK ' if s.state not in ('corrupt', 'missing') else 'BAD'} {s.id}: {s.state}"
            + (f" ({s.detail})" if s.detail else "")
            for s in rows
        ]
        _emit(
            as_json,
            {"ok": not bad, "models": [s.as_json() for s in rows]},
            "\n".join(lines) or "No installed models to verify.",
        )
        if bad:
            raise typer.Exit(1)


@app.command()
def add(
    source: str = typer.Argument(..., help="A local file or an https:// URL."),
    kind: str | None = typer.Option(
        None, "--kind", help=f"Model kind if it cannot be detected ({'|'.join(KIND_FOLDERS)})."
    ),
    model_id: str | None = typer.Option(None, "--id", help="ID to register it under."),
    allow_pickle: bool = typer.Option(
        False, "--allow-pickle", help="Allow a pickle-based file (.ckpt/.pt/.bin). Risky."
    ),
    link: bool = typer.Option(False, "--link", help="Symlink a local file instead of copying."),
    as_json: bool = JSON_OPT,
) -> None:
    """Add your own model. Only safetensors/GGUF unless --allow-pickle."""
    with _errors(as_json):
        m = _manager()
        with Downloader(tokens=load_tokens()) as dl:
            s = m.add(
                source,
                kind=kind,
                model_id=model_id,
                allow_pickle=allow_pickle,
                link=link,
                downloader=dl,
                warn=lambda msg: typer.echo(msg, err=True),
            )
        _emit(
            as_json, s.as_json(), f"Added {s.id} ({s.kind}, {s.base or 'base unknown'}): {s.path}"
        )


@app.command()
def remove(
    model_id: str,
    delete_file: bool = typer.Option(
        False, "--delete-file", help="For a user model: also delete its file."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask before deleting a file."),
    as_json: bool = JSON_OPT,
) -> None:
    """Delete a curated model's file, or unregister one of your models."""
    with _errors(as_json):
        m = _manager()
        s = m.status(model_id)
        deletes = s.path is not None and (s.origin == "manifest" or delete_file)
        if deletes and not yes:
            if not sys.stdin.isatty():
                raise ModelError(f"This deletes {s.path}; pass --yes to confirm.")
            if not typer.confirm(f"Delete {s.path}?", default=False, err=True):
                raise typer.Exit(1)
        msg = m.remove(model_id, delete_file=delete_file)
        _emit(as_json, {"id": model_id, "message": msg}, msg)


def _set_enabled(model_id: str, enabled: bool, as_json: bool) -> None:
    with _errors(as_json):
        _manager().set_enabled(model_id, enabled)
        word = "enabled" if enabled else "disabled"
        _emit(as_json, {"id": model_id, "enabled": enabled}, f"{model_id} {word}.")


@app.command()
def enable(model_id: str, as_json: bool = JSON_OPT) -> None:
    """Allow recipes to use a model again."""
    _set_enabled(model_id, True, as_json)


@app.command()
def disable(model_id: str, as_json: bool = JSON_OPT) -> None:
    """Hide a model from recipes without deleting it."""
    _set_enabled(model_id, False, as_json)


@app.command()
def licences(as_json: bool = JSON_OPT) -> None:
    """Show every curated model's licence, commercial-use flag and your acknowledgements."""
    with _errors(as_json):
        m = _manager()
        acks = m.licences.all()
        rows: list[dict[str, Any]] = []
        for e in m.manifest:
            ack = acks.get(e.id)
            rows.append(
                {
                    "id": e.id,
                    "name": e.name,
                    "licence": e.licence.name,
                    "url": e.licence.url,
                    "commercial_use": e.licence.commercial_use,
                    "flags": list(e.licence.flags),
                    "needs_acknowledgement": e.licence.needs_acknowledgement,
                    "accepted_at": ack.accepted_at
                    if ack and ack.licence == e.licence.name
                    else None,
                }
            )
        lines = [
            f"{r['id']:30} {r['licence']:26} commercial: {'yes' if r['commercial_use'] else 'NO':3}"
            f"  {', '.join(r['flags']) or '-':18} "
            + (
                f"accepted {r['accepted_at']}"
                if r["accepted_at"]
                else (
                    "not accepted yet"
                    if r["needs_acknowledgement"]
                    else "no acknowledgement needed"
                )
            )
            for r in rows
        ]
        _emit(as_json, {"licences": rows, "file": str(m.licences.path)}, "\n".join(lines))
