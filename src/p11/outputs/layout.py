"""Output file layout (spec R7, S6).

``<root>/YYYY-MM-DD/<template-slug|adhoc>/<HHMMSS>-<seed>[-<step>].png``. Every directory P11
creates here is ``0700``; the image file is reserved with an exclusive create (``0600``) so two jobs
finishing in the same second never overwrite each other (the second gets ``-2``, ``-3`` …).
The root is always passed in; this module never decides where outputs live.
"""

from __future__ import annotations

import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

ADHOC = "adhoc"
MAX_SLUG = 64
_NON_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(text: str, fallback: str = "untitled", max_length: int = MAX_SLUG) -> str:
    """Lower-case ``[a-z0-9-]`` only, no leading/trailing/double hyphens, never empty."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = _NON_SLUG.sub("-", ascii_text.lower()).strip("-")
    slug = slug[:max_length].rstrip("-")
    return slug or fallback


def template_dir_name(template_slug: str | None) -> str:
    if template_slug is None:
        return ADHOC
    slug = slugify(template_slug)
    # A template literally named "adhoc" must not share the ad-hoc folder.
    return f"{slug}-template" if slug == ADHOC else slug


def output_dir(root: Path, now: datetime, template_slug: str | None) -> Path:
    """The (created, ``0700``) directory for outputs of ``template_slug`` on ``now``'s date."""
    day = root / now.strftime("%Y-%m-%d")
    target = day / template_dir_name(template_slug)
    for d in (root, day, target):
        d.mkdir(mode=0o700, parents=d is root, exist_ok=True)
        d.chmod(0o700)
    return target


def output_path(
    root: Path,
    now: datetime,
    template_slug: str | None,
    seed: int,
    step: int | str | None = None,
    suffix: str = ".png",
) -> Path:
    """Reserve and return a new, empty output file (created ``0600``)."""
    if seed < 0:
        raise ValueError("seed must not be negative")
    stem = f"{now.strftime('%H%M%S')}-{seed}"
    if step is not None:
        stem += f"-{slugify(str(step), fallback='step', max_length=32)}"
    directory = output_dir(root, now, template_slug)
    for n in range(1, 10_000):
        name = f"{stem}{'' if n == 1 else f'-{n}'}{suffix}"
        path = directory / name
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        os.close(fd)
        return path
    raise FileExistsError(f"too many outputs named {stem} in {directory}")
