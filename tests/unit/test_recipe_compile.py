import json
import os
import random
from pathlib import Path
from typing import Any

import pytest
from tests.helpers import recipe

from p11.recipe import compile as c
from p11.recipe.compile import (
    CompileError,
    Conditioning,
    SlotBindingError,
    UnsupportedStepError,
    compile,
    register_modifier,
    register_step,
    resolve_seed,
)
from p11.recipe.model import (
    FaceSwap,
    FileRef,
    FixedSeed,
    Generate,
    IncrementSeed,
    Inpaint,
    LoraRef,
    ModelRef,
    Pose,
    RandomSeed,
    SamplerOverride,
    Slot,
    TextOverlay,
    Upscale,
)
from p11.recipe.presets import ASPECTS, STYLES
from p11.recipe.registry import (
    PROVISIONAL_DEFAULT_SET,
    ModelInfo,
    SamplerDefaults,
    StaticRegistry,
)

GOLDEN = Path(__file__).resolve().parents[1] / "golden" / "compile"
REG = PROVISIONAL_DEFAULT_SET
# Placeholder manifest IDs for tests that should not depend on the real default set.
FAKE = StaticRegistry(
    [
        ModelInfo("ckpt-a", "checkpoint", "a.safetensors", "a" * 64, "sdxl",
                  SamplerDefaults("euler", "normal", 20, 7.0, 2, 0)),
        ModelInfo("ckpt-b15", "checkpoint", "b.safetensors", None, "sd15",
                  SamplerDefaults("euler", "normal", 20, 7.0)),
        ModelInfo("ckpt-nodefaults", "checkpoint", "n.safetensors", None, "sdxl"),
        ModelInfo("ckpt-nofamily", "checkpoint", "f.safetensors", None, None,
                  SamplerDefaults("euler", "normal", 20, 7.0)),
        ModelInfo("lora-x", "lora", "x.safetensors"),
        ModelInfo("vae-x", "vae", "vae.safetensors"),
        ModelInfo("up-2x", "upscale", "2x.safetensors", scale=2),
        ModelInfo("up-4x", "upscale", "4x.safetensors", scale=4),
        ModelInfo("4x-nomos-webphoto-realplksr", "upscale", "default-up.safetensors", scale=4),
    ]
)  # fmt: skip


def nodes_of(graph: c.EngineGraph, cls: str) -> list[dict[str, Any]]:
    return [n for n in graph.nodes.values() if n["class_type"] == cls]


def one(graph: c.EngineGraph, cls: str) -> dict[str, Any]:
    found = nodes_of(graph, cls)
    assert len(found) == 1, f"{cls}: {len(found)}"
    return found[0]["inputs"]  # type: ignore[no-any-return]


def check_links(graph: c.EngineGraph) -> None:
    """Every link points at an existing node; the save node is the declared output."""
    for nid, node in graph.nodes.items():
        for value in node["inputs"].values():
            if isinstance(value, list):
                assert value[0] in graph.nodes and value[0] != nid
    assert graph.nodes[graph.output_node]["class_type"] == "SaveImage"


# ---------------------------------------------------------------------------------------------
# Golden graphs: every aspect preset x style preset with the default model (reviewed by eye).


def golden_recipe(aspect: str, style: str) -> Any:
    return recipe(
        Generate(prompt="a lighthouse on a rocky coast at dusk", style=style, aspect=aspect),
        id=f"golden-{style}",
    )


CASES = [(a, s) for a in ASPECTS for s in STYLES]


@pytest.mark.parametrize(("aspect", "style"), CASES)
def test_golden_graphs(aspect: str, style: str) -> None:
    graphs = compile(golden_recipe(aspect, style), {}, REG)
    assert len(graphs) == 1
    g = graphs[0]
    check_links(g)
    name = f"{aspect.replace(':', 'x')}__{style}.json"
    path = GOLDEN / name
    pretty = json.dumps(g.nodes, sort_keys=True, indent=1, ensure_ascii=False) + "\n"
    if os.environ.get("P11_UPDATE_GOLDEN") == "1":
        path.write_text(pretty, encoding="utf-8")
    assert path.exists(), f"missing golden {name}; run with P11_UPDATE_GOLDEN=1 and review it"
    assert path.read_text(encoding="utf-8") == pretty
    assert json.dumps(json.loads(pretty), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode() == g.to_json()  # fmt: skip


def test_recompile_is_byte_identical() -> None:
    r = recipe(
        Generate(prompt="ünïcode ☕ prompt", aspect="16:9-2560x1440", quality=True), Upscale()
    )
    first = [g.to_json() for g in compile(r, {}, REG)]
    for _ in range(3):
        assert [g.to_json() for g in compile(r, {}, REG)] == first


def test_wallpaper_model_chain_matches_adr_0010() -> None:
    (g,) = compile(recipe(Generate(prompt="x", aspect="16:9-1920x1080")), {}, REG)
    assert one(g, "EmptyLatentImage") == {"width": 1344, "height": 768, "batch_size": 1}
    assert one(g, "UpscaleModelLoader")["model_name"] == "4xNomosWebPhoto_RealPLKSR.safetensors"
    scale = one(g, "ImageScale")
    assert (scale["width"], scale["height"], scale["upscale_method"]) == (1920, 1080, "lanczos")
    ks = one(g, "KSampler")
    assert (ks["sampler_name"], ks["scheduler"], ks["steps"], ks["cfg"]) == (
        "dpmpp_sde", "karras", 5, 1.5,
    )  # fmt: skip
    assert one(g, "VAELoader")["vae_name"] == "sdxl_vae.safetensors"
    assert g.size == (1920, 1080)
    assert g.models == ("realvisxl5-lightning", "sdxl-vae-fp16-fix", "4x-nomos-webphoto-realplksr")


def test_quality_chain_is_latent_refinement() -> None:
    (g,) = compile(recipe(Generate(prompt="x", aspect="16:9-2560x1440", quality=True)), {}, REG)
    up = one(g, "LatentUpscale")
    assert (up["width"], up["height"], up["upscale_method"]) == (2560, 1440, "bislerp")
    hires = [n for n in g.nodes.values() if n.get("_meta", {}).get("title") == "hires"]
    assert len(hires) == 1
    assert hires[0]["inputs"]["denoise"] == 0.45 and hires[0]["inputs"]["steps"] == 3
    assert hires[0]["inputs"]["seed"] == 1112
    assert one(g, "VAEDecodeTiled")["tile_size"] == 512
    assert not nodes_of(g, "UpscaleModelLoader")


def test_both_chain() -> None:
    (g,) = compile(recipe(Generate(prompt="x", chain="both")), {}, REG)
    assert one(g, "VAEEncodeTiled")["tile_size"] == 512
    hires = [n for n in nodes_of(g, "KSampler") if n.get("_meta", {}).get("title") == "hires"]
    assert hires[0]["inputs"]["denoise"] == 0.3
    check_links(g)


def test_quality_model_full_steps() -> None:
    r = recipe(Generate(prompt="x", model=ModelRef(manifest_id="juggernautxl9"), quality=True))
    (g,) = compile(r, {}, REG)
    base, hires = nodes_of(g, "KSampler")
    assert base["inputs"]["steps"] == 30 and hires["inputs"]["steps"] == 15
    assert not nodes_of(g, "VAELoader")  # baked VAE
    assert one(g, "VAEDecodeTiled")["vae"] == ["1", 2]


def test_avatar_is_native_portrait() -> None:
    (g,) = compile(recipe(Generate(prompt="x", style="3d-animated-avatar")), {}, REG)
    assert one(g, "EmptyLatentImage")["width"] == 896
    assert one(g, "EmptyLatentImage")["height"] == 1152
    assert nodes_of(g, "VAEDecode") and not nodes_of(g, "ImageScale")
    assert g.size == (896, 1152)
    text = nodes_of(g, "CLIPTextEncode")[0]["inputs"]["text"]
    assert text.startswith("3d animated character, bobblehead caricature, x")


def test_sd15_bucket_and_no_style() -> None:
    r = recipe(Generate(prompt="  plain  ", style=None, negative="ugly",
                        model=ModelRef(manifest_id="realisticvision6")))  # fmt: skip
    (g,) = compile(r, {}, REG)
    assert one(g, "EmptyLatentImage")["width"] == 1024
    assert one(g, "EmptyLatentImage")["height"] == 576
    texts = [n["inputs"]["text"] for n in nodes_of(g, "CLIPTextEncode")]
    assert texts == ["plain", "ugly"]
    assert one(g, "VAELoader")["vae_name"] == "vae-ft-mse-840000-ema-pruned.safetensors"


def test_square_preset_native_for_sdxl_upscaled_for_sd15() -> None:
    (g,) = compile(recipe(Generate(prompt="x", aspect="1:1-1024")), {}, REG)
    assert g.size == (1024, 1024) and not nodes_of(g, "ImageScale")
    r = recipe(Generate(prompt="x", aspect="1:1-1024", model=ModelRef(manifest_id="ckpt-b15")))
    (g,) = compile(r, {}, FAKE)
    assert one(g, "EmptyLatentImage")["width"] == 512 and g.size == (1024, 1024)


def test_forced_native_chain_returns_bucket_size() -> None:
    (g,) = compile(recipe(Generate(prompt="x", chain="native")), {}, REG)
    assert g.size == (1344, 768)


def test_overrides_loras_clip_skip_batch() -> None:
    r = recipe(
        Generate(
            prompt="x",
            model=ModelRef(manifest_id="ckpt-a"),
            vae=ModelRef(manifest_id="vae-x"),
            loras=(LoraRef(model=ModelRef(manifest_id="lora-x"), strength_model=0.6),),
            sampler=SamplerOverride(sampler_name="dpmpp_2m", scheduler="karras", steps=12, cfg=0.0),
            batch_size=3,
            chain="model",
        )
    )
    (g,) = compile(r, {}, FAKE)
    ks = nodes_of(g, "KSampler")[0]["inputs"]
    assert (ks["sampler_name"], ks["scheduler"], ks["steps"], ks["cfg"]) == (
        "dpmpp_2m", "karras", 12, 0.0,
    )  # fmt: skip
    lora = one(g, "LoraLoader")
    assert lora["strength_model"] == 0.6 and lora["lora_name"] == "x.safetensors"
    assert one(g, "CLIPSetLastLayer")["stop_at_clip_layer"] == -2
    assert one(g, "CLIPSetLastLayer")["clip"] == [nodes_of_id(g, "LoraLoader"), 1]
    assert ks["model"] == [nodes_of_id(g, "LoraLoader"), 0]
    assert one(g, "EmptyLatentImage")["batch_size"] == 3
    assert one(g, "VAELoader")["vae_name"] == "vae.safetensors"


def nodes_of_id(g: c.EngineGraph, cls: str) -> str:
    return next(k for k, n in g.nodes.items() if n["class_type"] == cls)


@pytest.mark.parametrize(
    ("override", "msg"),
    [
        (SamplerOverride(sampler_name="warp"), "unknown sampler 'warp'"),
        (SamplerOverride(scheduler="wobbly"), "unknown scheduler 'wobbly'"),
    ],
)
def test_sampler_names_checked(override: SamplerOverride, msg: str) -> None:
    with pytest.raises(CompileError, match=msg):
        compile(recipe(Generate(prompt="x", sampler=override)), {}, REG)


def test_sampler_lists_match_pinned_engine() -> None:
    assert {"dpmpp_sde", "dpmpp_2m", "euler", "uni_pc_bh2"} <= c.SAMPLERS
    assert {"karras", "sgm_uniform", "normal"} <= c.SCHEDULERS


@pytest.mark.parametrize(
    ("step", "msg"),
    [
        (Generate(prompt="x", model=ModelRef(manifest_id="nope")), "not installed"),
        (Generate(prompt="x", model=ModelRef(manifest_id="lora-x")), "is a lora, not a checkpoint"),
        (Generate(prompt="x", model=ModelRef(manifest_id="ckpt-a", sha256="b" * 64)), "hash"),
        (Generate(prompt="x", model=ModelRef(manifest_id="ckpt-nodefaults")), "no sampler"),
        (Generate(prompt="x", model=ModelRef(manifest_id="ckpt-nofamily")), "no model family"),
        (Generate(prompt="x", style="noir", model=ModelRef(manifest_id="ckpt-a")), "unknown style"),
        (Generate(prompt="x", aspect="9:16", model=ModelRef(manifest_id="ckpt-a")), "aspect"),
    ],
)
def test_model_and_preset_errors(step: Generate, msg: str) -> None:
    with pytest.raises(CompileError, match=msg):
        compile(recipe(step), {}, FAKE)


def test_matching_hash_accepted() -> None:
    r = recipe(Generate(prompt="x", aspect="1:1-1024",
                        model=ModelRef(manifest_id="ckpt-a", sha256="a" * 64)))  # fmt: skip
    assert compile(r, {}, FAKE)[0].models == ("ckpt-a",)


# ---------------------------------------------------------------------------------------------
# Slots and bindings


def slot_recipe() -> Any:
    return recipe(
        Generate(prompt="logo for {{brand}}, {{extra}}", style="logo-flat"),
        Upscale(image_slot="photo"),
        slots=(
            Slot(name="brand", kind="text", label="Product name"),
            Slot(name="extra", kind="text", required=False),
            Slot(name="photo", kind="image", required=False),
        ),
    )


def test_text_slot_substituted() -> None:
    g0, _ = compile(slot_recipe(), {"brand": "Acme", "photo": FileRef(ref="u/1.png")}, REG)
    text = nodes_of(g0, "CLIPTextEncode")[0]["inputs"]["text"]
    assert "logo for Acme, clean lines" in text and "{{" not in text
    g0, _ = compile(
        slot_recipe(), {"brand": "A", "extra": "neon", "photo": FileRef(ref="1.png")}, REG
    )
    assert "logo for A, neon, clean" in nodes_of(g0, "CLIPTextEncode")[0]["inputs"]["text"]


def test_missing_required_slot_names_it() -> None:
    with pytest.raises(SlotBindingError, match="Product name") as exc:
        compile(slot_recipe(), {}, REG)
    assert exc.value.slot == "brand"
    with pytest.raises(SlotBindingError, match="brand"):
        compile(slot_recipe(), {"brand": "   "}, REG)


def test_text_default_used() -> None:
    r = recipe(
        Generate(prompt="{{t}}", style=None), slots=(Slot(name="t", kind="text", default="d"),)
    )
    (g,) = compile(r, {}, REG)
    assert nodes_of(g, "CLIPTextEncode")[0]["inputs"]["text"] == "d"


def test_unknown_binding_rejected() -> None:
    with pytest.raises(SlotBindingError, match="no input called 'nope'"):
        compile(slot_recipe(), {"brand": "A", "nope": "x"}, REG)


def test_binding_types_checked() -> None:
    with pytest.raises(SlotBindingError, match="needs text"):
        compile(slot_recipe(), {"brand": FileRef(ref="a.png")}, REG)
    with pytest.raises(SlotBindingError, match="needs a file"):
        compile(slot_recipe(), {"brand": "A", "photo": "a.png"}, REG)


def test_optional_image_slot_unbound_but_used() -> None:
    with pytest.raises(SlotBindingError, match="needs an image for 'photo'"):
        compile(slot_recipe(), {"brand": "A"}, REG)


def test_image_slot_becomes_graph_input() -> None:
    _, g1 = compile(slot_recipe(), {"brand": "A", "photo": FileRef(ref="u/1.png")}, REG)
    (inp,) = g1.inputs
    assert inp.source == "slot" and inp.slot == "photo" and inp.file == FileRef(ref="u/1.png")
    assert g1.nodes[inp.node_id] == {
        "class_type": "LoadImage",
        "inputs": {"image": "p11:slot:photo"},
    }


# ---------------------------------------------------------------------------------------------
# Upscale step


def test_upscale_after_generate_uses_previous_output() -> None:
    _, g1 = compile(recipe(Generate(prompt="x"), Upscale(scale=2.0)), {}, REG)
    (inp,) = g1.inputs
    assert (inp.source, inp.step, inp.placeholder) == ("step", 0, "p11:step:0")
    assert one(g1, "ImageScaleBy")["scale_by"] == 0.5  # 4x model, then x0.5 = 2x overall
    assert g1.size is None
    assert one(g1, "SaveImage")["filename_prefix"] == "p11/step-01"


def test_upscale_model_exact_factor_and_target() -> None:
    r = recipe(
        Upscale(scale=2.0, upscaler=ModelRef(manifest_id="up-2x")),
        source_image=FileRef(ref="s.png"),
    )
    (g,) = compile(r, {}, FAKE)
    assert not nodes_of(g, "ImageScaleBy") and g.inputs[0].source == "source"
    r = recipe(Upscale(width=3000, height=2000), source_image=FileRef(ref="s.png"))
    (g,) = compile(r, {}, REG)
    assert one(g, "ImageScale")["width"] == 3000 and g.size == (3000, 2000)


def test_upscale_without_input_fails() -> None:
    with pytest.raises(CompileError, match="needs an input image"):
        compile(recipe(Upscale()), {}, REG)


@pytest.mark.parametrize("chain", ["latent", "both"])
def test_upscale_refinement_uses_generate_model_and_prompt(chain: str) -> None:
    r = recipe(
        Generate(prompt="castle", model=ModelRef(manifest_id="juggernautxl9")),
        Upscale(chain=chain, width=2048, height=2048),  # type: ignore[arg-type]
    )
    _, g = compile(r, {}, REG)
    assert one(g, "CheckpointLoaderSimple")["ckpt_name"].startswith("Juggernaut")
    assert "castle" in nodes_of(g, "CLIPTextEncode")[0]["inputs"]["text"]
    ks = one(g, "KSampler")
    assert ks["denoise"] == (0.45 if chain == "latent" else 0.3)
    assert ks["steps"] == 15
    assert g.size == (2048, 2048)
    check_links(g)


def test_upscale_latent_scale_by_and_own_prompt() -> None:
    r = recipe(
        Upscale(chain="latent", scale=1.5, prompt="sharp", denoise=0.2,
                model=ModelRef(manifest_id="ckpt-a")),
        source_image=FileRef(ref="s.png"),
    )  # fmt: skip
    (g,) = compile(r, {}, FAKE)
    assert one(g, "LatentUpscaleBy")["scale_by"] == 1.5
    assert one(g, "KSampler")["denoise"] == 0.2 and one(g, "KSampler")["steps"] == 10
    assert one(g, "CLIPSetLastLayer")["stop_at_clip_layer"] == -2
    assert nodes_of(g, "CLIPTextEncode")[0]["inputs"]["text"] == "sharp"


def test_upscale_refinement_model_needs_defaults() -> None:
    r = recipe(Upscale(chain="latent", model=ModelRef(manifest_id="ckpt-nodefaults")),
               source_image=FileRef(ref="s.png"))  # fmt: skip
    with pytest.raises(CompileError, match="no sampler defaults"):
        compile(r, {}, FAKE)


def test_upscale_refinement_with_vae_override_model() -> None:
    r = recipe(Upscale(chain="both"), source_image=FileRef(ref="s.png"))
    (g,) = compile(r, {}, REG)
    assert one(g, "VAELoader")["vae_name"] == "sdxl_vae.safetensors"
    assert one(g, "ImageScaleBy")["scale_by"] == 0.5


# ---------------------------------------------------------------------------------------------
# Seeds


def test_seed_strategies() -> None:
    assert resolve_seed(FixedSeed(value=7), 5) == 7
    assert resolve_seed(IncrementSeed(start=10), 3) == 13
    assert resolve_seed(RandomSeed(), rng=random.Random(1)) == resolve_seed(
        RandomSeed(), rng=random.Random(1)
    )
    with pytest.raises(CompileError, match="random source"):
        resolve_seed(RandomSeed())


def test_compile_seed_handling() -> None:
    assert compile(recipe(seed=IncrementSeed(start=5)), {}, REG, run_index=2)[0].seed == 7
    assert compile(recipe(seed=RandomSeed()), {}, REG, seed=42)[0].seed == 42
    with pytest.raises(CompileError, match="random source"):
        compile(recipe(seed=RandomSeed()), {}, REG)
    with pytest.raises(CompileError, match="out of range"):
        compile(recipe(), {}, REG, seed=-1)


# ---------------------------------------------------------------------------------------------
# Extension point


def test_later_phase_steps_are_unsupported_for_now() -> None:
    slots = (Slot(name="mask", kind="mask"), Slot(name="face", kind="face_image"),
             Slot(name="pose", kind="image"))  # fmt: skip
    for step, phase in [
        (FaceSwap(face_slot="face"), "Phase 12"),
        (TextOverlay(text="Hi"), "Phase 14"),
        (Pose(pose_slot="pose"), "Phase 12"),
    ]:
        with pytest.raises(UnsupportedStepError, match=phase):
            files = {n: FileRef(ref=f"{n}.png") for n in ("mask", "face", "pose")}
            compile(recipe(Generate(prompt="x"), step, slots=slots), files, REG)


def test_register_step_and_modifier(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(c, "_STEP_COMPILERS", dict(c._STEP_COMPILERS))
    monkeypatch.setattr(c, "_MODIFIERS", dict(c._MODIFIERS))
    c.unregister("inpaint")

    def fake_inpaint(step: Inpaint, ctx: c.CompileContext, g: c.GraphBuilder) -> c.Ref:
        img = ctx.load_image(g, step.image_slot)
        mask = ctx.load_mask(g, step.mask_slot)
        return g.node("ImageCompositeMasked", destination=img, source=img, mask=mask)

    def fake_pose(step: Pose, ctx: c.CompileContext, g: c.GraphBuilder,
                  cond: Conditioning) -> Conditioning:  # fmt: skip
        pos = g.node("ConditioningZeroOut", conditioning=cond.positive)
        return Conditioning(cond.model, cond.clip, cond.vae, pos, cond.negative, cond.family)

    register_step("inpaint", fake_inpaint)
    register_modifier("pose", fake_pose)
    with pytest.raises(ValueError, match="already registered"):
        register_step("inpaint", fake_inpaint)
    with pytest.raises(ValueError, match="already registered"):
        register_modifier("pose", fake_pose)
    register_step("inpaint", fake_inpaint, replace=True)

    r = recipe(
        Generate(prompt="x"),
        Pose(pose_slot="pose"),
        Inpaint(mask_slot="mask"),
        slots=(Slot(name="pose", kind="image"), Slot(name="mask", kind="mask")),
    )
    g0, g1 = compile(r, {"pose": FileRef(ref="p.png"), "mask": FileRef(ref="m.png")}, REG)
    zero = nodes_of_id(g0, "ConditioningZeroOut")
    assert nodes_of(g0, "KSampler")[0]["inputs"]["positive"] == [zero, 0]
    assert g1.step_index == 2 and [i.source for i in g1.inputs] == ["step", "slot"]
    assert g1.inputs[0].step == 0
    c.unregister("inpaint")
    with pytest.raises(UnsupportedStepError):
        compile(r, {"pose": FileRef(ref="p.png"), "mask": FileRef(ref="m.png")}, REG)
