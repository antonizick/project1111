import { describe, expect, it } from "vitest";
import { models, presets } from "../../test/fakes";
import type { RunRecord } from "../../api/types";
import {
  clampCount,
  defaultsFor,
  effectiveAspect,
  effectiveModel,
  fromRecord,
  initialForm,
  recipeName,
  resetAdvanced,
  toRecipe,
  upscaleRecipe,
  withModel,
  withStyle,
} from "./form";

const at = { id: "abc123", now: new Date("2026-11-03T10:00:00Z") };

describe("form → recipe", () => {
  it("Simple mode leaves model and sampler to the presets and manifest", () => {
    const r = toRecipe({ ...initialForm, prompt: "  a lighthouse at dusk " }, at);
    expect(r).toMatchObject({
      schema_version: 1,
      id: "abc123",
      name: "a lighthouse at dusk",
      seed: { kind: "random" },
      created_at: "2026-11-03T10:00:00.000Z",
      source_image: null,
      slots: [],
    });
    expect(r.steps).toEqual([
      {
        type: "generate",
        prompt: "a lighthouse at dusk",
        negative: "",
        style: "photoreal",
        aspect: null,
        model: null,
        loras: [],
        sampler: null,
        chain: null,
        quality: false,
        batch_size: 1,
      },
    ]);
  });

  it("Advanced values become overrides; a locked seed increments across a batch", () => {
    const form = {
      ...initialForm,
      prompt: "x",
      model: "juggernautxl9",
      negative: "blur",
      loras: [{ id: "detail-lora", weight: 0.6 }],
      steps: 12,
      cfg: 3,
      chain: "latent" as const,
      seedLocked: true,
      seed: 42,
      aspect: "16:9-2560x1440",
    };
    const step = toRecipe(form, at).steps[0];
    expect(step).toMatchObject({
      model: { manifest_id: "juggernautxl9" },
      negative: "blur",
      aspect: "16:9-2560x1440",
      chain: "latent",
      loras: [{ model: { manifest_id: "detail-lora" }, strength_model: 0.6, strength_clip: 0.6 }],
      sampler: { sampler_name: null, scheduler: null, steps: 12, cfg: 3 },
    });
    expect(toRecipe(form, at).seed).toEqual({ kind: "increment", start: 42 });
    expect(toRecipe({ ...form, seedLocked: false }, at).seed).toEqual({ kind: "random" });
  });

  it("switching style moves the aspect to the style's default", () => {
    const logo = withStyle(initialForm, "logo-flat", presets);
    expect(logo.aspect).toBe("logo-1:1");
    expect(effectiveAspect(initialForm, presets)).toBe("16:9-1920x1080");
    expect(effectiveAspect({ ...initialForm, aspect: "1:1-1024" }, presets)).toBe("1:1-1024");
  });

  it("advanced defaults come from the chosen model's manifest entry", () => {
    expect(effectiveModel(initialForm, presets)).toBe("realvisxl5-lightning");
    expect(defaultsFor("realvisxl5-lightning", models)?.steps).toBe(5);
    expect(defaultsFor("juggernautxl9", models)?.sampler_name).toBe("dpmpp_2m");
    expect(defaultsFor("nope", models)).toBeNull();
    const changed = withModel({ ...initialForm, steps: 9, cfg: 2 }, "juggernautxl9");
    expect(changed).toMatchObject({ model: "juggernautxl9", steps: null, cfg: null });
    expect(resetAdvanced({ ...changed, negative: "x", seedLocked: true })).toMatchObject({
      model: null,
      negative: "",
      seedLocked: false,
    });
  });

  it("names, counts and the upscale follow-up", () => {
    expect(recipeName("")).toBe("Untitled");
    expect(recipeName("a".repeat(80))).toHaveLength(58);
    expect([clampCount(0), clampCount(9), clampCount(2.4), clampCount(NaN)]).toEqual([1, 4, 2, 1]);
    const up = upscaleRecipe(7, "sea", at);
    expect(up.source_image).toEqual({ ref: "gallery/7" });
    expect(up.steps).toEqual([{ type: "upscale", image_slot: null, chain: "model", scale: 2 }]);
  });
});

describe("open as recipe", () => {
  const record = (steps: unknown[]): RunRecord =>
    ({
      recipe: { ...toRecipe({ ...initialForm, prompt: "p" }, at), steps },
      bindings: {},
      seed: 777,
      template: null,
      timings: {},
      model_hashes: {},
    }) as RunRecord;

  it("round-trips the generate settings and locks the seed", () => {
    const form = {
      ...initialForm,
      prompt: "harbour at night",
      style: "logo-3d",
      aspect: "logo-1:1",
      model: "juggernautxl9",
      steps: 20,
      chain: "both" as const,
    };
    const out = fromRecord(record(toRecipe(form, at).steps));
    expect(out?.partial).toBe(false);
    expect(out?.form).toEqual({ ...form, seedLocked: true, seed: 777 });
  });

  it("flags recipes with more than the generate step, and rejects ones without", () => {
    const gen = toRecipe({ ...initialForm, prompt: "p" }, at).steps[0];
    expect(fromRecord(record([gen, { type: "upscale", chain: "model" }]))?.partial).toBe(true);
    expect(fromRecord(record([{ type: "upscale", chain: "model" }]))).toBeNull();
  });
});
