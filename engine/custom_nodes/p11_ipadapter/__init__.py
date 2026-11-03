"""P11's IP-Adapter node pack (Phase 12, ADR-0031): style and character reference images.

ComfyUI v0.43.0 ships no IP-Adapter node, and P11 needs one to give a generation a style or a
character. This pack is **P11's own source** in the repo (MIT, like the project), installed into the
engine's ``custom_nodes/`` by ``scripts/engine_setup.sh`` and the only pack ComfyUI is allowed to
load (``--disable-all-custom-nodes --whitelist-custom-nodes p11_ipadapter``, S3). It is pinned with
the engine: ``engine/engine.lock.toml`` records the pack's name, source and the digest of the file,
and the installer refuses to run a different copy.

What it does: ``P11IPAdapterLoader`` reads an IP-Adapter checkpoint (``ipadapter/`` folder);
``P11IPAdapterApply`` projects the reference image's CLIP-ViT-H features to cross-attention tokens
and patches every cross-attention layer of the UNet so that, in addition to the text, those tokens
are attended to, with a weight that can fade in and out over the denoising run.

Checkpoint layout (read from ``ip-adapter-plus_sdxl_vit-h.safetensors`` and
``ip-adapter-plus-face_sdxl_vit-h.safetensors``, h94/IP-Adapter, checked 2026-11-03 10:20 CST):

- ``image_proj.latents [1, 16, 1280]``, ``image_proj.proj_in.{weight,bias} [1280, 1280]``,
  ``image_proj.layers.<0-3>.0.{norm1,norm2,to_q,to_kv,to_out}`` (Perceiver attention, heads 20 x
  dim_head 64), ``image_proj.layers.<0-3>.1.{0,1,3}`` (LayerNorm + MLP, ratio 4),
  ``image_proj.proj_out.{weight [2048, 1280], bias [2048]}``, ``image_proj.norm_out.* [2048]``.
- ``ip_adapter.<N>.{to_k_ip,to_v_ip}.weight [inner_dim, 2048]`` for 70 cross-attention layers,
  ``N`` odd from 1 to 139.

Layer order. The ``ip_adapter.N`` numbering follows the order in which the UNet's modules are
enumerated: **input blocks, output blocks, middle block** (the shapes settle it: the checkpoint is
640 x4, 1280 x50, 640 x6, 1280 x10, which is only that order). ``apply`` walks the engine's own
UNet in the same order and checks every layer's width against the checkpoint's, so a mismatched
mapping refuses to run instead of producing a wrong picture.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger("p11.ipadapter")

# The clip_vision embedding width of the encoders P11 ships (ViT-H/14); the projector needs it.
EMBED_DIM = 1280


class P11IPAdapterError(RuntimeError):
    pass


# ---------------------------------------------------------------------------------------------
# Checkpoint


def _load_checkpoint(path: str) -> dict:
    """State dict of an IP-Adapter checkpoint (safetensors or torch pickle; both are pinned)."""
    try:
        from safetensors.torch import load_file
    except ImportError:  # pragma: no cover - the engine venv always has it
        load_file = None
    if path.endswith(".safetensors") and load_file is not None:
        sd = load_file(path)
    else:
        import torch

        sd = torch.load(path, map_location="cpu", weights_only=True)
        if isinstance(sd, dict) and "state_dict" in sd:
            sd = sd["state_dict"]
    if not isinstance(sd, dict):
        raise P11IPAdapterError(f"{os.path.basename(path)}: not a model file")
    return sd


def _float32(tensor):
    import torch

    return tensor.to(torch.float32).cpu() if tensor.is_floating_point() else tensor


def _nest(flat: dict) -> dict:
    """``{"a.b.c": t}`` -> ``{"a": {"b": {"c": t}}}`` (groups of keys, like the checkpoint)."""
    out: dict = {}
    for key, value in flat.items():
        head, _, tail = key.partition(".")
        if tail:
            out.setdefault(head, {})[tail] = value
        else:
            out[head] = value
    return {k: _nest(v) if isinstance(v, dict) else v for k, v in out.items()}


def _flatten(group: dict, prefix: str = "") -> dict:
    """``{"norm1": {"weight": t}}`` -> ``{"norm1.weight": t}``, the inverse of ``_nest``."""
    out = {}
    for key, value in group.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(_flatten(value, f"{name}."))
        else:
            out[name] = value
    return out


class P11IPAdapter:
    """One checkpoint: the image projector and the per-layer key/value projections."""

    def __init__(self, path: str) -> None:
        sd = _load_checkpoint(path)
        self.name = os.path.basename(path)
        self.proj = _nest({k.removeprefix("image_proj."): _float32(v) for k, v in sd.items()
                           if k.startswith("image_proj.")})  # fmt: skip
        raw_layers = self.proj.pop("layers", {})
        self.proj["layers"] = [
            [_flatten(raw_layers[str(i)]["0"]), _flatten(raw_layers[str(i)]["1"])]
            for i in range(len(raw_layers))
        ]
        self.layers: dict[int, dict[str, object]] = {}
        for key, value in sd.items():
            if not key.startswith("ip_adapter."):
                continue
            _, idx, weight_name, _ = key.split(".")
            self.layers.setdefault(int(idx), {})[weight_name] = _float32(value)
        if not self.layers or not self.proj:
            raise P11IPAdapterError(f"{self.name}: this is not an IP-Adapter checkpoint")
        self.num_layers = len(self.layers)

    def ordered_layers(self) -> list[dict[str, object]]:
        return [self.layers[idx] for idx in sorted(self.layers)]

    def layer_widths(self) -> list[int]:
        return [int(t["to_k_ip"].shape[0]) for t in self.ordered_layers()]

    def has_latents(self) -> bool:
        return "latents" in self.proj


class P11IPAdapterLoader:
    """Load an IP-Adapter checkpoint from the ``ipadapter`` folder."""

    @classmethod
    def INPUT_TYPES(cls):
        import folder_paths

        return {
            "required": {
                "ipadapter_file": (folder_paths.get_filename_list("ipadapter"),),
            }
        }

    RETURN_TYPES = ("IPADAPTER",)
    FUNCTION = "load"
    CATEGORY = "P11"

    def load(self, ipadapter_file):
        import folder_paths

        path = folder_paths.get_full_path_or_raise("ipadapter", ipadapter_file)
        return (_get_ipadapter(path),)


_CACHE: dict[str, P11IPAdapter] = {}


def _get_ipadapter(path: str) -> P11IPAdapter:
    found = _CACHE.get(path)
    if found is None:
        found = P11IPAdapter(path)
        _CACHE[path] = found
    return found


# ---------------------------------------------------------------------------------------------
# Image projection (IP-Adapter-Plus resampler)


def _layer_norm(x, weight, bias):
    import torch

    return torch.nn.functional.layer_norm(x, (x.shape[-1],), weight, bias)


def _linear(x, weight, bias=None):
    import torch

    out = torch.nn.functional.linear(x, weight)
    return out if bias is None else out + bias


def _attention(q, k, v, heads):
    """Standard multi-head attention on ``[B, T, heads * dim_head]`` tensors."""
    import torch

    b, _tq, _ = q.shape
    dim_head = q.shape[-1] // heads

    def shape(t):
        return t.view(b, -1, heads, dim_head).transpose(1, 2)

    def unshape(t):
        return t.transpose(1, 2).reshape(b, -1, heads * dim_head)

    q2, k2, v2 = shape(q), shape(k), shape(v)
    scores = (q2 * (dim_head**-0.5)) @ k2.transpose(-1, -2)
    probs = torch.softmax(scores.float(), dim=-1).to(q.dtype)
    return unshape(probs @ v2)


def _perceiver(layer, x, latents):
    """One resampler layer: cross-attend the latents to the image tokens, then an MLP."""
    import torch

    attn, mlp = layer[0], layer[1]
    x_n = _layer_norm(x, attn["norm2.weight"], attn["norm2.bias"])
    lat_n = _layer_norm(latents, attn["norm1.weight"], attn["norm1.bias"])
    kv_in = torch.cat((x_n, lat_n), dim=1)
    kv = _linear(kv_in, attn["to_kv.weight"])
    k, v = kv.chunk(2, dim=-1)
    q = _linear(lat_n, attn["to_q.weight"])
    out = _attention(q, k, v, q.shape[-1] // 64)
    latents = latents + _linear(out, attn["to_out.weight"])
    h = _layer_norm(latents, mlp["0.weight"], mlp["0.bias"])
    h = _linear(h, mlp["1.weight"])
    h = _activation(h)
    h = _linear(h, mlp["3.weight"])
    return latents + h


def _activation(x):
    import torch

    return torch.nn.functional.gelu(x)


def project_image(proj: dict, clip_output, device, dtype):
    """CLIP-Vision output -> the IP-Adapter tokens ``[B, T, 2048]`` (or the single-token path)."""
    import torch

    hidden = getattr(clip_output, "penultimate_hidden_states", None)
    pooled = getattr(clip_output, "image_embeds", None)
    if "latents" in proj:  # IP-Adapter-Plus / plus-face: a 16-token resampler
        if hidden is None:
            raise P11IPAdapterError(
                "This reference model needs a CLIP vision encoder that returns hidden states."
            )
        x = hidden.to(device, torch.float32)
        if x.shape[-1] != EMBED_DIM:
            raise P11IPAdapterError(
                f"This reference model expects a {EMBED_DIM}-wide CLIP vision encoder "
                f"(got {x.shape[-1]}). Install the one P11 ships."
            )
        latents = proj["latents"].to(device, torch.float32).repeat(x.shape[0], 1, 1)
        for attn, mlp in proj["layers"]:
            latents = _perceiver((attn, mlp), x, latents)
        out = _linear(latents, proj["proj_out"]["weight"], proj["proj_out"]["bias"])
        return _layer_norm(out, proj["norm_out"]["weight"], proj["norm_out"]["bias"]).to(dtype)
    if pooled is None:
        raise P11IPAdapterError("This reference model needs the pooled CLIP vision embedding.")
    out = _linear(
        pooled.to(device, torch.float32), proj["proj"]["weight"], proj["proj"].get("bias")
    )
    return _layer_norm(out, proj["norm"]["weight"], proj["norm"]["bias"]).to(dtype)


# ---------------------------------------------------------------------------------------------
# Model patch


def _unet_of(model):
    inner = model.model if hasattr(model, "model") else model
    unet = getattr(inner, "diffusion_model", None)
    if unet is None:
        raise P11IPAdapterError("This P11 build only supports UNet diffusion models.")
    return unet


def _attn2_blocks(unet):
    """``(block key, inner dim)`` for every cross-attention layer, in checkpoint order.

    Order: input blocks, then output blocks, then the middle block (see the module docstring).
    """
    import torch.nn as nn

    out = []

    def blocks(modules, name, count):
        for i, blk in enumerate(modules):
            for sub in blk:
                for ti, tr in enumerate(getattr(sub, "transformer_blocks", []) or []):
                    attn2 = getattr(tr, "attn2", None)
                    if isinstance(attn2, nn.Module) or attn2 is not None:
                        out.append(((name, i, ti), int(attn2.to_k.weight.shape[0])))

    blocks(unet.input_blocks, "input", None)
    blocks(unet.output_blocks, "output", None)
    for ti, tr in enumerate(getattr(unet.middle_block[1], "transformer_blocks", []) or []):
        attn2 = getattr(tr, "attn2", None)
        if attn2 is not None:
            out.append((("middle", 0, ti), int(attn2.to_k.weight.shape[0])))
    return out


class P11IPAdapterApply:
    """Patch a model to also attend to the reference image's tokens."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "ipadapter": ("IPADAPTER",),
                "clip_vision_output": ("CLIP_VISION_OUTPUT",),
                "weight": ("FLOAT", {"default": 0.7, "min": 0.0, "max": 2.0, "step": 0.01}),
                "start": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "end": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
            }
        }

    RETURN_TYPES = ("MODEL",)
    FUNCTION = "apply"
    CATEGORY = "P11"

    def apply(self, model, ipadapter, clip_vision_output, weight, start, end):
        if end < start:
            raise P11IPAdapterError("The reference's End must not be before its Start.")
        import torch

        # Built on the CPU and moved per call: the model may still be offloaded at apply time.
        tokens = project_image(
            ipadapter.proj, clip_vision_output, torch.device("cpu"), torch.float32
        )
        blocks = _attn2_blocks(_unet_of(model))
        widths = ipadapter.layer_widths()
        if len(blocks) != len(widths):
            raise P11IPAdapterError(
                f"This model has {len(blocks)} cross-attention layers but {ipadapter.name} has "
                f"{len(widths)}; this reference model does not fit this model."
            )
        patches = []
        for (key, dim), layer in zip(blocks, ipadapter.ordered_layers(), strict=True):
            width = int(layer["to_k_ip"].shape[0])
            if width != dim:
                raise P11IPAdapterError(
                    f"{ipadapter.name} does not match this model (layer {key}: {width} vs {dim})."
                )
            patches.append((key, layer))
        patched = model.clone()
        for key, layer in patches:
            patched.set_model_attn2_replace(
                _make_patch(layer, tokens, float(weight), float(start), float(end)),
                key[0],
                key[1],
                key[2],
            )
        return (patched,)


def _model_dtype(model):
    try:
        param = next(model.model.diffusion_model.parameters())
        return param.device, param.dtype
    except Exception:
        import torch

        return torch.device("cpu"), torch.float32


def _make_patch(layer, tokens, weight, start, end):
    to_k = layer["to_k_ip"]
    to_v = layer["to_v_ip"]
    state = {"sigma_max": None}

    def patch(n, context, value, extra_options):
        import comfy.ldm.modules.attention as c_attn

        heads = extra_options["n_heads"]
        out = c_attn.optimized_attention(n, context, value, heads)
        w = _gate(state, extra_options, weight, start, end)
        if w == 0.0:
            return out
        n.shape[0] // max(1, len(extra_options.get("cond_or_uncond") or [1]))
        emb = tokens
        if emb.shape[0] == 1 and n.shape[0] > 1:
            emb = emb.expand(n.shape[0], -1, -1)
        elif emb.shape[0] != n.shape[0]:
            emb = emb.repeat(n.shape[0], 1, 1) if emb.shape[0] == 1 else emb[: n.shape[0]]
        emb = emb.to(n.device, n.dtype)
        k_ip = _linear(emb, to_k.to(n.device, n.dtype))
        v_ip = _linear(emb, to_v.to(n.device, n.dtype))
        out_ip = c_attn.optimized_attention(n, k_ip, v_ip, heads)
        return out + w * out_ip

    return patch


def _gate(state, extra_options, weight, start, end):
    """Weight at this point of the run: 0 outside ``[start, end]`` of the denoising progress."""
    if weight == 0.0:
        return 0.0
    sigma = extra_options.get("sigmas")
    if sigma is None:
        return weight
    value = float(sigma.reshape(-1)[0]) if hasattr(sigma, "reshape") else float(sigma)
    if state["sigma_max"] is None:
        state["sigma_max"] = max(value, 1e-6)
    progress = min(1.0, max(0.0, 1.0 - value / state["sigma_max"]))
    if progress < start or progress > end:
        return 0.0
    return weight


NODE_CLASS_MAPPINGS = {
    "P11IPAdapterLoader": P11IPAdapterLoader,
    "P11IPAdapterApply": P11IPAdapterApply,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "P11IPAdapterLoader": "P11 IP-Adapter loader",
    "P11IPAdapterApply": "P11 IP-Adapter apply (style or character)",
}
__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
