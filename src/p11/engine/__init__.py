"""Engine protocol, ComfyUI client, FakeEngine and process supervisor (Phase 05).

Nothing outside this package imports ``p11.engine.comfy``; everything else takes an ``Engine``.
"""

from __future__ import annotations

from p11.config import Settings
from p11.engine.base import Engine


def create_engine(settings: Settings, *, fake: bool = False) -> Engine:
    """The engine P11 runs with: the pinned ComfyUI, or the FakeEngine for ``--fake`` and tests."""
    if fake:
        from p11.engine.fake import FakeEngine

        return FakeEngine()
    from p11.engine.comfy import ComfyEngine, EngineConfig

    return ComfyEngine(EngineConfig.default(settings))
