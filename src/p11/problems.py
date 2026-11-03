"""A problem found by a health check, for ``p11 doctor`` (Phase 07) and the UI."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class Problem:
    severity: Severity
    #: Stable machine-readable code, e.g. ``models.missing-default``.
    code: str
    #: Plain English: what is wrong.
    message: str
    #: What to do about it (usually a command).
    hint: str = ""

    def as_json(self) -> dict[str, str]:
        return asdict(self)
