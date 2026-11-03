// Background form state -> recipe JSON (schema v1 `replace_background` step,
// src/p11/recipe/model.py). Pure: the ID and the clock are passed in. The subject is the
// recipe's `source_image`; the (auto or refined) mask is a `mask` slot bound to an upload; the
// background photo is a `background_image` slot, or a flat colour/transparent fill.

import type { Presets, Recipe, SeedStrategy } from "../../api/types";
import { MAX_SEED, recipeName } from "../generate/form";

export type Harmonize = "off" | "light" | "strong";

/** Tuned in Phase 11 (docs/P11_BENCHMARKS.md -> Background replacement, ADR-0027). */
export const HARMONIZE_DENOISE: Record<Harmonize, number> = {
  off: 0,
  light: 0.25,
  strong: 0.45,
};

export const DEFAULTS = {
  harmonize: "light" as Harmonize,
  colourMatch: true,
  feather: 8,
  fit: "cover" as const,
  shadow: false,
};

export type BackgroundForm = {
  harmonize: Harmonize;
  colourMatch: boolean;
  feather: number;
  fit: "cover" | "contain";
  backgroundX: number;
  backgroundY: number;
  subjectScale: number;
  subjectX: number;
  subjectY: number;
  shadow: boolean;
};

export function initialBackground(): BackgroundForm {
  return {
    harmonize: DEFAULTS.harmonize,
    colourMatch: DEFAULTS.colourMatch,
    feather: DEFAULTS.feather,
    fit: DEFAULTS.fit,
    backgroundX: 0.5,
    backgroundY: 0.5,
    subjectScale: 1,
    subjectX: 0.5,
    subjectY: 0.5,
    shadow: DEFAULTS.shadow,
  };
}

export const MASK_SLOT = "mask";
export const BACKGROUND_SLOT = "background";

/** What the subject is: a gallery image (an edit chain) or an uploaded photo. */
export type Source =
  | { kind: "gallery"; id: number; ref: string; url: string; width: number; height: number }
  | { kind: "upload"; id: string; ref: string; url: string; width: number; height: number };

export type BackgroundChoice =
  | { kind: "photo"; ref: string; url: string }
  | { kind: "gallery"; ref: string; url: string }
  | { kind: "colour"; colour: string; transparent: boolean };

export function sourceRef(source: Source): string {
  return source.ref;
}

/** The aspect preset whose output ratio is closest to the subject's (for Describe). */
export function nearestAspect(
  presets: Presets | null,
  width: number,
  height: number,
): string | null {
  if (!presets || width <= 0 || height <= 0) return null;
  const ratio = width / height;
  let best: { id: string; d: number } | null = null;
  for (const a of presets.aspects) {
    if (!a.output) continue;
    const d = Math.abs(a.output[0] / a.output[1] - ratio);
    if (!best || d < best.d) best = { id: a.id, d };
  }
  return best?.id ?? null;
}

/** A one-step recipe that generates a described background (the view applies it after). */
export function describeRecipe(
  prompt: string,
  aspect: string | null,
  { id, now }: { id: string; now: Date },
): Recipe {
  return {
    schema_version: 1,
    id,
    name: recipeName(`Background: ${prompt}`),
    tags: [],
    folder: "",
    steps: [
      {
        type: "generate",
        prompt,
        negative: "",
        style: "photoreal",
        aspect,
        model: null,
        loras: [],
        sampler: null,
        chain: null,
        quality: false,
        batch_size: 1,
      },
    ],
    slots: [],
    seed: { kind: "random" },
    created_at: now.toISOString(),
    source_image: null,
  };
}

export function backgroundRecipe(
  form: BackgroundForm,
  source: Source,
  background: BackgroundChoice,
  { id, now, seed }: { id: string; now: Date; seed: number | null },
): Recipe {
  const photo = background.kind !== "colour";
  const colour =
    background.kind === "colour"
      ? background.transparent
        ? "#00000000"
        : background.colour
      : null;
  const seedStrategy: SeedStrategy =
    seed === null
      ? { kind: "random" }
      : { kind: "fixed", value: Math.min(MAX_SEED, Math.max(0, Math.round(seed))) };
  return {
    schema_version: 1,
    id,
    name: recipeName("Background"),
    tags: [],
    folder: "",
    steps: [
      {
        type: "replace_background",
        image_slot: null,
        background_slot: photo ? BACKGROUND_SLOT : null,
        background_colour: colour,
        mask_mode: "manual",
        mask_slot: MASK_SLOT,
        mask_png: null,
        segmentation_model: null,
        colour_match: form.colourMatch,
        colour_match_strength: 1,
        feather_px: form.feather,
        relight: photo && form.harmonize !== "off",
        relight_denoise: HARMONIZE_DENOISE[form.harmonize],
        prompt: "",
        negative: "",
        fit: form.fit,
        background_x: form.backgroundX,
        background_y: form.backgroundY,
        subject_scale: form.subjectScale,
        subject_x: form.subjectX,
        subject_y: form.subjectY,
        shadow: form.shadow,
      },
    ],
    slots: [
      { name: MASK_SLOT, kind: "mask", label: "Subject mask", required: true, default: null },
      ...(photo
        ? [
            {
              name: BACKGROUND_SLOT,
              kind: "background_image" as const,
              label: "Background photo",
              required: true,
              default: null,
            },
          ]
        : []),
    ],
    seed: seedStrategy,
    created_at: now.toISOString(),
    source_image: { ref: sourceRef(source) },
  };
}
