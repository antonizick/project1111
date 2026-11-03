"""Model file formats by content, never by extension (spec S4).

``.safetensors`` and GGUF hold only tensors and metadata and load by default. Pickle-based files
(``.ckpt``, ``.pt``, ``.pth``, ``.bin``: raw pickle or PyTorch's zip-of-pickle) can run code when
loaded and are refused unless the user opts in per file.
"""

from __future__ import annotations

import json
import struct
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

Format = Literal["safetensors", "gguf", "pickle", "torch-zip", "unknown"]
SAFE_FORMATS: frozenset[str] = frozenset({"safetensors", "gguf"})
PICKLE_FORMATS: frozenset[str] = frozenset({"pickle", "torch-zip"})

#: A safetensors header larger than this is not a model we want to parse (it is read into memory).
MAX_HEADER = 100 * 1024 * 1024

PICKLE_RISK = (
    "Pickle-based model files (.ckpt, .pt, .pth, .bin) can run arbitrary code on this computer "
    "when they are loaded. Only allow one you trust completely, and prefer a .safetensors version."
)


class FormatError(ValueError):
    pass


def sniff(path: Path) -> Format:
    with path.open("rb") as f:
        head = f.read(16)
    if head[:4] == b"GGUF":
        return "gguf"
    if head[:4] == b"PK\x03\x04":
        return "torch-zip" if _zip_has_pickle(path) else "unknown"
    if len(head) >= 2 and head[0] == 0x80 and 2 <= head[1] <= 5:
        return "pickle"
    if len(head) >= 9:
        (n,) = struct.unpack("<Q", head[:8])
        if 2 <= n <= MAX_HEADER and head[8:9] == b"{":
            try:
                read_safetensors_header(path)
            except FormatError:
                return "unknown"
            return "safetensors"
    return "unknown"


def _zip_has_pickle(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as z:
            return any(n.endswith(".pkl") for n in z.namelist())
    except zipfile.BadZipFile:
        return False


def read_safetensors_header(path: Path) -> dict[str, Any]:
    """The JSON header of a safetensors file (tensor names → dtype/shape/offsets)."""
    size = path.stat().st_size
    with path.open("rb") as f:
        raw = f.read(8)
        if len(raw) < 8:
            raise FormatError(f"{path.name}: too short to be a safetensors file")
        (n,) = struct.unpack("<Q", raw)
        if n > MAX_HEADER or n + 8 > size:
            raise FormatError(f"{path.name}: implausible safetensors header length {n}")
        try:
            header = json.loads(f.read(n))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise FormatError(f"{path.name}: safetensors header is not JSON") from None
    if not isinstance(header, dict):
        raise FormatError(f"{path.name}: safetensors header is not an object")
    return header


def detect(header: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """Best-effort ``(kind, base)`` from tensor names; ``None`` where it cannot tell.

    Key patterns checked against the six default/full models on 2026-11-02 19:45 CST: SDXL
    checkpoints carry ``conditioner.embedders.1`` (the second text encoder), SD 1.5 ones
    ``cond_stage_model.transformer``; VAEs are bare ``encoder.``/``decoder.`` (SDXL and SD 1.5
    VAEs share one layout, so their base stays unknown); kohya LoRAs use ``lora_unet_``, with
    ``lora_te2_`` only on SDXL.
    """
    keys = [k for k in header if k != "__metadata__"]
    if not keys:
        return None, None

    def has(prefix: str) -> bool:
        return any(k.startswith(prefix) for k in keys)

    if has("model.diffusion_model."):
        if has("conditioner.embedders.1."):
            return "checkpoint", "sdxl"
        if has("cond_stage_model."):
            return "checkpoint", "sd15"
        return "checkpoint", None
    if any("lora_" in k or ".lora." in k or "lora_A" in k for k in keys):
        if has("lora_te2_") or has("lora_te1_"):
            return "lora", "sdxl"
        if has("lora_te_"):
            return "lora", "sd15"
        return "lora", None
    if has("encoder.") and has("decoder."):
        return "vae", None
    return None, None
