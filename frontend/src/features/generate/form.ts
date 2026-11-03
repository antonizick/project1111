// Generate form state ⇄ recipe JSON (schema v1, src/p11/recipe/model.py). Pure: the ID and the
// clock are passed in. Simple mode fills prompt, style, aspect and count; the Advanced drawer's
// values are `null` until changed, so the compiler keeps using the model's manifest defaults.

import type {
  Chain,
  GenerateStep,
  ModelInfo,
  Presets,
  Recipe,
  RunRecord,
  SamplerDefaults,
  SeedStrategy,
} from "../../api/types";

export const MAX_SEED = 2 ** 53 - 1;
export const MAX_BATCH = 4;

export type LoraChoice = { id: string; weight: number };

export type FormState = {
  prompt: string;
  style: string;
  /** Aspect preset ID; null = the style's default aspect. */
  aspect: string | null;
  count: number;
  // Advanced (R18)
  /** Checkpoint manifest ID; null = the style's model. */
  model: string | null;
  negative: string;
  loras: LoraChoice[];
  sampler: string | null;
  scheduler: string | null;
  steps: number | null;
  cfg: number | null;
  chain: Chain | null;
  /** The wallpaper Quality upscale toggle (Phase 14): model upscale + refinement pass. */
  quality: boolean;
  seedLocked: boolean;
  seed: number | null;
};

export const DEFAULT_STYLE = "photoreal";

export const initialForm: FormState = {
  prompt: "",
  style: DEFAULT_STYLE,
  aspect: null,
  count: 1,
  model: null,
  negative: "",
  loras: [],
  sampler: null,
  scheduler: null,
  steps: null,
  cfg: null,
  chain: null,
  quality: false,
  seedLocked: false,
  seed: null,
};

export function styleOf(presets: Presets | null, id: string) {
  return presets?.styles.find((s) => s.id === id) ?? null;
}

/** The aspect the form will use: the chosen one, else the style's default. */
export function effectiveAspect(form: FormState, presets: Presets | null): string | null {
  return form.aspect ?? styleOf(presets, form.style)?.aspect ?? null;
}

/** The checkpoint the form will use: the chosen one, else the style's model. */
export function effectiveModel(form: FormState, presets: Presets | null): string | null {
  return form.model ?? styleOf(presets, form.style)?.model ?? null;
}

export function defaultsFor(
  modelId: string | null,
  models: ModelInfo[] | null,
): SamplerDefaults | null {
  return models?.find((m) => m.id === modelId)?.defaults ?? null;
}

/** Choosing a style also moves the aspect to that style's default (e.g. logos are square). */
export function withStyle(form: FormState, style: string, presets: Presets | null): FormState {
  return { ...form, style, aspect: styleOf(presets, style)?.aspect ?? null };
}

/** Choosing another model drops sampler overrides, since its defaults differ. */
export function withModel(form: FormState, model: string | null): FormState {
  return { ...form, model, sampler: null, scheduler: null, steps: null, cfg: null };
}

export function resetAdvanced(form: FormState): FormState {
  return {
    ...form,
    model: null,
    negative: "",
    loras: [],
    sampler: null,
    scheduler: null,
    steps: null,
    cfg: null,
    chain: null,
    quality: false,
    seedLocked: false,
  };
}

export function clampCount(n: number): number {
  return Math.min(MAX_BATCH, Math.max(1, Math.round(Number.isFinite(n) ? n : 1)));
}

export function seedStrategy(form: FormState): SeedStrategy {
  if (!form.seedLocked || form.seed === null) return { kind: "random" };
  // Run i of a batch uses seed + i, so a locked batch is reproducible but not four copies.
  return { kind: "increment", start: Math.min(MAX_SEED, Math.max(0, Math.floor(form.seed))) };
}

export function recipeName(prompt: string): string {
  const text = prompt.trim().replace(/\s+/g, " ");
  if (!text) return "Untitled";
  return text.length > 60 ? `${text.slice(0, 57)}…` : text;
}

export function newRecipeId(): string {
  return crypto.randomUUID().replace(/-/g, "");
}

export function toRecipe(form: FormState, { id, now }: { id: string; now: Date }): Recipe {
  const sampler =
    form.sampler !== null || form.scheduler !== null || form.steps !== null || form.cfg !== null
      ? { sampler_name: form.sampler, scheduler: form.scheduler, steps: form.steps, cfg: form.cfg }
      : null;
  const step: GenerateStep = {
    type: "generate",
    prompt: form.prompt.trim(),
    negative: form.negative.trim(),
    style: form.style,
    aspect: form.aspect,
    model: form.model ? { manifest_id: form.model } : null,
    loras: form.loras.map((l) => ({
      model: { manifest_id: l.id },
      strength_model: l.weight,
      strength_clip: l.weight,
    })),
    sampler,
    chain: form.chain,
    quality: form.quality,
    batch_size: 1,
  };
  return {
    schema_version: 1,
    id,
    name: recipeName(form.prompt),
    tags: [],
    folder: "",
    steps: [step],
    slots: [],
    seed: seedStrategy(form),
    created_at: now.toISOString(),
    source_image: null,
  };
}

/** Load a run record ("open as recipe") into the form. `partial` is set when steps were left out. */
export function fromRecord(record: RunRecord): { form: FormState; partial: boolean } | null {
  const steps = record.recipe.steps;
  const gen = steps.find((s): s is GenerateStep => s.type === "generate");
  if (!gen) return null;
  const sampler = gen.sampler;
  const form: FormState = {
    ...initialForm,
    prompt: gen.prompt,
    style: gen.style ?? DEFAULT_STYLE,
    aspect: gen.aspect,
    model: gen.model?.manifest_id ?? null,
    negative: gen.negative ?? "",
    loras: (gen.loras ?? []).map((l) => ({ id: l.model.manifest_id, weight: l.strength_model })),
    sampler: sampler?.sampler_name ?? null,
    scheduler: sampler?.scheduler ?? null,
    steps: sampler?.steps ?? null,
    cfg: sampler?.cfg ?? null,
    chain: gen.chain,
    quality: gen.quality ?? false,
    // Re-opening an image reproduces it: its seed is locked.
    seedLocked: true,
    seed: record.seed,
  };
  return { form, partial: steps.length > 1 || record.recipe.slots.length > 0 };
}

export type UpscaleOptions = {
  /** Speed (model only) or Quality (model + refinement pass, Phase 14). */
  quality?: boolean;
  /** ×1.5 / ×2 …; ignored when a target size is given. */
  scale?: number;
  width?: number;
  height?: number;
};

/** Recipe for the Upscale follow-up: the gallery image at a factor or a target size. */
export function upscaleRecipe(
  imageId: number,
  prompt: string,
  { id, now }: { id: string; now: Date },
  options: UpscaleOptions = {},
): Recipe {
  const target =
    options.width !== undefined && options.height !== undefined
      ? { width: options.width, height: options.height, scale: null }
      : { scale: options.scale ?? 2 };
  return {
    schema_version: 1,
    id,
    name: recipeName(`Upscale: ${prompt}`),
    tags: [],
    folder: "",
    steps: [
      {
        type: "upscale",
        image_slot: null,
        chain: options.quality ? "latent" : "model",
        ...target,
      },
    ],
    slots: [],
    seed: { kind: "random" },
    created_at: now.toISOString(),
    source_image: { ref: `gallery/${imageId}` },
  };
}
