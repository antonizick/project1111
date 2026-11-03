"""Acceptance: ``recipe/``, ``outputs/`` and ``templates/`` do no network I/O (Phase 04)."""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "p11"
NETWORK = {"socket", "ssl", "http", "urllib", "httpx", "requests", "websockets", "aiohttp",
           "ftplib", "smtplib", "asyncio", "uvicorn", "fastapi"}  # fmt: skip
#: The recipe package is fully pure: no filesystem or process access either.
PURE = {"recipe": {"os", "pathlib", "sqlite3", "shutil", "subprocess", "tempfile"}}


def imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            out |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module.split(".")[0])
    return out


@pytest.mark.parametrize("package", ["recipe", "outputs", "templates"])
def test_no_network_imports(package: str) -> None:
    for path in (SRC / package).glob("*.py"):
        bad = imports(path) & (NETWORK | PURE.get(package, set()))
        assert not bad, f"{path.name} imports {sorted(bad)}"


def test_no_default_roots_in_outputs_and_templates() -> None:
    """Filesystem access only through injected roots: no imports of p11.paths or config."""
    for package in ("outputs", "templates"):
        for path in (SRC / package).glob("*.py"):
            text = path.read_text()
            assert "paths" not in imports(path) and "from ..paths" not in text
            assert "from ..config" not in text and "Path.home" not in text
