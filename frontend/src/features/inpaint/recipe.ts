// Inpaint form state → recipe JSON (schema v1 `inpaint` step, src/p11/recipe/model.py). Pure: the
// ID and the clock are passed in. The mask is a `mask` slot bound to the uploaded painting.

import type { Recipe, SeedStrategy } from "../../api/types";
import { MAX_SEED, recipeName } from "../generate/form";

export type Preset = "subtle" | "balanced" | "major";

export const PRESETS: { id: Preset; label: string; about: string }[] = [
  { id: "subtle", label: "Subtle fix", about: "Keep the shapes, fix details (skin, hands, text)." },
  { id: "balanced", label: "Change", about: "Change what is there, keep the layout." },
  { id: "major", label: "Replace", about: "Paint something new in the area." },
];

/** What the base image is: a gallery image (an edit chain) or an uploaded photo. */
export type Source =
  | {
      kind: "gallery";
      id: number;
      url: string;
      width: number;
      height: number;
      model: string | null;
    }
  | { kind: "upload"; id: string; url: string; width: number; height: number };

export type InpaintForm = {
  prompt: string;
  preset: Preset;
  /** Advanced denoise (0..1); null = the preset's tuned strength. */
  denoise: number | null;
  crop: boolean;
  blur: number;
  padding: number;
  steps: number | null;
  seed: number | null;
};

export const DEFAULTS = { blur: 12, padding: 48, grow: 8 };

export function initialInpaint(prompt = ""): InpaintForm {
  return {
    prompt,
    preset: "balanced",
    denoise: null,
    crop: false,
    blur: DEFAULTS.blur,
    padding: DEFAULTS.padding,
    steps: null,
    seed: null,
  };
}

export const MASK_SLOT = "mask";

export function sourceRef(source: Source): string {
  return source.kind === "gallery" ? `gallery/${source.id}` : source.id;
}

export function inpaintRecipe(
  form: InpaintForm,
  source: Source,
  { id, now }: { id: string; now: Date },
): Recipe {
  const seed: SeedStrategy =
    form.seed === null
      ? { kind: "random" }
      : { kind: "fixed", value: Math.min(MAX_SEED, Math.max(0, Math.round(form.seed))) };
  return {
    schema_version: 1,
    id,
    name: recipeName(`Inpaint: ${form.prompt}`),
    tags: [],
    folder: "",
    steps: [
      {
        type: "inpaint",
        image_slot: null,
        mask_slot: MASK_SLOT,
        mask_png: null,
        prompt: form.prompt.trim(),
        negative: "",
        denoise: form.denoise ?? 0.6,
        denoise_preset: form.denoise === null ? form.preset : null,
        grow_mask_px: DEFAULTS.grow,
        mask_blur_px: form.blur,
        crop: form.crop,
        padding_px: form.padding,
        model: source.kind === "gallery" && source.model ? { manifest_id: source.model } : null,
        sampler:
          form.steps === null
            ? null
            : { sampler_name: null, scheduler: null, steps: form.steps, cfg: null },
      },
    ],
    slots: [{ name: MASK_SLOT, kind: "mask", label: "Mask", required: true, default: null }],
    seed,
    created_at: now.toISOString(),
    source_image: { ref: sourceRef(source) },
  };
}
