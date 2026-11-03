"""Model manifest, verified downloader and registry (Phase 06).

- ``manifest``: the hash-pinned curated set (``models/manifest.toml``).
- ``download``: HTTPS-only resumable downloads with streaming SHA-256.
- ``formats``: content sniffing and the S4 safetensors/pickle policy.
- ``registry``: ``ModelManager`` (install, verify, add, remove, enable) and the compiler registry.
- ``doctor``: ``check()`` for ``p11 doctor``.
"""

from __future__ import annotations

from p11.problems import Problem

from .doctor import check

__all__ = ["Problem", "check"]
