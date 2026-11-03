"""Template store: recipes as JSON files under ``<root>/<folder>/<slug>.json`` (spec R6, §4).

The root is passed in (the app uses ``paths.config_dir() / "templates"``). File and folder names
are always slugs P11 generates, so nothing a user types or imports can name a path outside the
root. Imports are validated and migrated before they are stored.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from ..outputs.layout import slugify
from ..recipe.migrate import RecipeFormatError, RecipeVersionError, loads
from ..recipe.model import Recipe

MAX_FOLDER_DEPTH = 3
MAX_IMPORT_BYTES = 1_000_000


class TemplateError(ValueError):
    pass


@dataclass(frozen=True)
class TemplateInfo:
    folder: str
    slug: str
    path: Path
    recipe: Recipe


def folder_path(folder: str) -> str:
    """``"Logos / Dark"`` → ``"logos/dark"``; empty for the top level."""
    slugs = (slugify(p, fallback="") for p in folder.replace("\\", "/").split("/"))
    parts = [p for p in slugs if p]
    if len(parts) > MAX_FOLDER_DEPTH:
        raise TemplateError(f"Folders can be at most {MAX_FOLDER_DEPTH} levels deep.")
    return "/".join(parts)


class TemplateStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _dir(self, folder: str) -> Path:
        rel = folder_path(folder)
        d = self.root / rel if rel else self.root
        resolved_root = self.root.resolve()
        if not d.resolve().is_relative_to(resolved_root):  # defence in depth; slugs cannot escape
            raise TemplateError("Template folder is outside the template directory.")
        return d

    def save(self, recipe: Recipe) -> TemplateInfo:
        """Store ``recipe``; replaces the file with the same recipe ID, else picks a free name."""
        directory = self._dir(recipe.folder)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        d = self.root
        for part in directory.relative_to(self.root).parts:
            d = d / part
            d.mkdir(mode=0o700, exist_ok=True)
        existing = self.find(recipe.id)
        if existing is not None and existing.path.parent != directory:
            existing.path.unlink()  # moved to another folder
            existing = None
        if existing is not None:
            path = existing.path
        else:
            base = slugify(recipe.name, fallback="template")
            path = directory / f"{base}.json"
            n = 2
            while path.exists():
                path = directory / f"{base}-{n}.json"
                n += 1
        tmp = path.with_name(f".{path.name}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(recipe.to_json())
            fh.write("\n")
        tmp.replace(path)
        return TemplateInfo(folder_path(recipe.folder), path.stem, path, recipe)

    def _files(self) -> Iterator[Path]:
        if not self.root.is_dir():
            return
        for path in sorted(self.root.rglob("*.json")):
            rel = path.relative_to(self.root)
            if path.name.startswith(".") or len(rel.parts) > MAX_FOLDER_DEPTH + 1:
                continue
            yield path

    def all(self) -> list[TemplateInfo]:
        """Every valid template; unreadable or invalid files are skipped (see ``problems``)."""
        out = []
        for path in self._files():
            try:
                recipe = loads(path.read_bytes())
            except (OSError, RecipeFormatError, RecipeVersionError):
                continue
            folder = path.parent.relative_to(self.root).as_posix()
            out.append(TemplateInfo("" if folder == "." else folder, path.stem, path, recipe))
        return out

    def problems(self) -> dict[Path, str]:
        """Template files that could not be read, with the reason (for the UI)."""
        out: dict[Path, str] = {}
        for path in self._files():
            try:
                loads(path.read_bytes())
            except (OSError, RecipeFormatError, RecipeVersionError) as exc:
                out[path] = str(exc)
        return out

    def find(self, recipe_id: str) -> TemplateInfo | None:
        return next((t for t in self.all() if t.recipe.id == recipe_id), None)

    def load(self, folder: str, slug: str) -> Recipe:
        if slug != slugify(slug):
            raise TemplateError("Not a template name.")
        path = self._dir(folder) / f"{slug}.json"
        if not path.is_file():
            raise TemplateError(f"No template {slug!r} in folder {folder or '(top level)'!r}.")
        return loads(path.read_bytes())

    def delete(self, recipe_id: str) -> bool:
        found = self.find(recipe_id)
        if found is None:
            return False
        found.path.unlink()
        return True

    def search(self, text: str = "", tag: str | None = None) -> list[TemplateInfo]:
        """Case-insensitive match of every word against name, tags and folder; optional tag."""
        words = text.lower().split()
        out = []
        for t in self.all():
            tags = {x.lower() for x in t.recipe.tags}
            if tag is not None and tag.lower() not in tags:
                continue
            hay = " ".join([t.recipe.name.lower(), *tags, t.folder.lower()])
            if all(w in hay for w in words):
                out.append(t)
        return sorted(out, key=lambda t: (t.folder, t.recipe.name.lower(), t.slug))

    def folders(self) -> list[str]:
        return sorted({t.folder for t in self.all()})

    def export(self, recipe_id: str) -> bytes:
        found = self.find(recipe_id)
        if found is None:
            raise TemplateError("No template with that ID.")
        return (found.recipe.to_json() + "\n").encode()

    def import_bytes(self, data: bytes, *, keep_id: bool = False) -> TemplateInfo:
        """Validate, migrate and store an exported template.

        By default the import gets a new ID, so importing the same file twice keeps both copies
        and never overwrites a local template.
        """
        if len(data) > MAX_IMPORT_BYTES:
            raise TemplateError("This file is too large to be a P11 template.")
        try:
            recipe = loads(data)
        except (RecipeFormatError, RecipeVersionError) as exc:
            raise TemplateError(str(exc)) from exc
        if not keep_id:
            recipe = recipe.model_copy(update={"id": uuid.uuid4().hex})
        return self.save(recipe)
