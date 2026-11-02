"""Build ComfyUI API graphs for the bake-off: native txt2img plus three upscale chains (ADR-0010)."""

from __future__ import annotations

from typing import Any

from .configs import ModelCfg, Sampler

Graph = dict[str, dict[str, Any]]
HIRES_DENOISE = {"latent": 0.45, "both": 0.3}


def build(m: ModelCfg, s: Sampler, prompt: str, negative: str, seed: int,
          out: tuple[int, int] | None, chain: str, upscaler: str, prefix: str) -> Graph:
    g: Graph = {}

    def node(cls: str, **inputs: Any) -> list[Any]:
        nid = str(len(g) + 1)
        g[nid] = {"class_type": cls, "inputs": inputs}
        return [nid, 0]

    ck = node("CheckpointLoaderSimple", ckpt_name=m.ckpt)
    model, clip = ck, [ck[0], 1]
    vae: list[Any] = [ck[0], 2]
    if m.vae:
        vae = node("VAELoader", vae_name=m.vae)
    if m.lora:
        lo = node("LoraLoader", model=model, clip=clip, lora_name=m.lora, strength_model=1.0, strength_clip=1.0)
        model, clip = lo, [lo[0], 1]
    pos = node("CLIPTextEncode", text=prompt, clip=clip)
    neg = node("CLIPTextEncode", text=negative, clip=clip)
    w, h = m.bucket
    lat = node("EmptyLatentImage", width=w, height=h, batch_size=1)
    base = node("KSampler", model=model, seed=seed, steps=s.steps, cfg=s.cfg, sampler_name=s.name,
                scheduler=s.scheduler, positive=pos, negative=neg, latent_image=lat, denoise=1.0)
    g[base[0]]["_meta"] = {"title": "base"}

    def hires(latent: list[Any], denoise: float) -> list[Any]:
        k = node("KSampler", model=model, seed=seed + 1, steps=s.hires_steps, cfg=s.cfg, sampler_name=s.name,
                 scheduler=s.scheduler, positive=pos, negative=neg, latent_image=latent, denoise=denoise)
        g[k[0]]["_meta"] = {"title": "hires"}
        return k

    def decode(latent: list[Any]) -> list[Any]:
        return node("VAEDecodeTiled", samples=latent, vae=vae, tile_size=512, overlap=64,
                    temporal_size=64, temporal_overlap=8)

    if out is None or chain == "native":
        img = node("VAEDecode", samples=base, vae=vae)
    elif chain == "latent":
        up = node("LatentUpscale", samples=base, upscale_method="bislerp", width=out[0], height=out[1],
                  crop="disabled")
        img = decode(hires(up, HIRES_DENOISE["latent"]))
    else:
        img = node("VAEDecode", samples=base, vae=vae)
        um = node("UpscaleModelLoader", model_name=upscaler)
        img = node("ImageUpscaleWithModel", upscale_model=um, image=img)
        img = node("ImageScale", image=img, upscale_method="lanczos", width=out[0], height=out[1], crop="disabled")
        if chain == "both":
            enc = node("VAEEncodeTiled", pixels=img, vae=vae, tile_size=512, overlap=64,
                       temporal_size=64, temporal_overlap=8)
            img = decode(hires(enc, HIRES_DENOISE["both"]))
    node("SaveImage", images=img, filename_prefix=prefix)
    return g


def base_node(g: Graph) -> str:
    return next(k for k, v in g.items() if v.get("_meta", {}).get("title") == "base")
