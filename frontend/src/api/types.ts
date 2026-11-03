// Shapes of the Studio API (docs/P11_ARCHITECTURE.md → Studio API; src/p11/api/routes/).
// Hand-written from the OpenAPI schema; only the fields the UI reads are typed.

export type JobState = "queued" | "running" | "paused" | "done" | "failed" | "cancelled";
export const FINISHED: ReadonlySet<JobState> = new Set(["done", "failed", "cancelled"]);

import type { Problem } from "./session";

export type { Problem };

export type Job = {
  id: string;
  state: JobState;
  name: string;
  count: number;
  template: string | null;
  created_at: string;
  updated_at: string;
  images: number[];
  progress: number;
  error: Problem | null;
  note: string | null;
};

export type ProgressEvent = {
  job: string;
  run: number;
  runs: number;
  graph: number;
  graphs: number;
  progress: number;
  step?: number;
  total?: number;
  title?: string | null;
};

export type PreviewEvent = { job: string; mime: string; data: string };

export type ImageEntry = {
  id: number;
  path: string;
  created_at: string;
  recipe_id: string;
  template: string | null;
  seed: number;
  model: string | null;
  width: number | null;
  height: number | null;
  favourite: boolean;
  parent_id: number | null;
  prompt: string;
  url: string;
  thumb: string;
};

export type GalleryPage = { items: ImageEntry[]; total: number; limit: number; offset: number };
export type Facets = { templates: string[]; models: string[] };
export type TrashInfo = { count: number; bytes: number };

export type GpuSample = {
  vram_used_mib: number;
  vram_total_mib: number;
  temp_c: number;
  power_w: number | null;
  sm_clock_mhz?: number | null;
  throttle_reasons: string[];
  thermal_throttled?: boolean;
};

export type EngineState = "stopped" | "starting" | "ready" | "stopping" | "failed" | string;

export type SystemInfo = {
  version: string;
  fake: boolean;
  started_at: string;
  port: number;
  engine: {
    state: EngineState;
    ready: boolean;
    vram_mode: string;
    version: string | null;
    last_error: string | null;
  };
  gpu: GpuSample | null;
  queue: { current: string | null; waiting: number };
};

export type Chain = "native" | "model" | "latent" | "both";

export type AspectPreset = {
  id: string;
  label: string;
  output: [number, number] | null;
  bucket: Record<string, [number, number]>;
  chain: Chain;
  quality_chain: Chain;
};

export type StylePreset = {
  id: string;
  label: string;
  aspect: string;
  model: string;
  tags: string[];
};

export type Presets = { aspects: AspectPreset[]; styles: StylePreset[] };

export type SamplerDefaults = {
  sampler_name: string;
  scheduler: string;
  steps: number;
  cfg: number;
  clip_skip: number;
  hires_steps: number;
};

export type ModelInfo = {
  id: string;
  name: string;
  kind: string;
  base: string | null;
  state: string;
  sets: string[];
  enabled: boolean;
  usable: boolean;
  family: string | null;
  defaults: SamplerDefaults | null;
  vae: string | null;
  licence: { name: string; commercial_use: boolean; flags: string[] } | null;
};

// Recipe schema v1 (src/p11/recipe/model.py). Only the parts the generate form writes.
export type ModelRef = { manifest_id: string; sha256?: string | null };

export type LoraRef = { model: ModelRef; strength_model: number; strength_clip: number };

export type SamplerOverride = {
  sampler_name: string | null;
  scheduler: string | null;
  steps: number | null;
  cfg: number | null;
  clip_skip?: number | null;
};

export type GenerateStep = {
  type: "generate";
  prompt: string;
  negative: string;
  style: string | null;
  aspect: string | null;
  model: ModelRef | null;
  vae?: ModelRef | null;
  loras: LoraRef[];
  sampler: SamplerOverride | null;
  chain: Chain | null;
  quality: boolean;
  batch_size: number;
};

export type Step = GenerateStep | ({ type: string } & Record<string, unknown>);

export type SeedStrategy =
  { kind: "random" } | { kind: "fixed"; value: number } | { kind: "increment"; start: number };

export type SlotKind = "text" | "image" | "face_image" | "background_image" | "mask" | "video";

export type Slot = {
  name: string;
  kind: SlotKind;
  label: string | null;
  required: boolean;
  default: string | null;
};

export type Recipe = {
  schema_version: 1;
  id: string;
  name: string;
  tags: string[];
  folder: string;
  steps: Step[];
  slots: Slot[];
  seed: SeedStrategy;
  created_at: string;
  source_image: { ref: string; sha256?: string | null } | null;
};

export type RunRecord = {
  recipe: Recipe;
  bindings: Record<string, unknown>;
  seed: number;
  template: string | null;
  timings: Record<string, number>;
  model_hashes: Record<string, string | null>;
};

export type Template = {
  id: string;
  name: string;
  folder: string;
  slug: string;
  tags: string[];
  slots: Slot[];
  recipe: Recipe;
  /** Newest image made from this template, for the card thumbnail. */
  last_image: ImageEntry | null;
};

export type Upload = { id: string; kind: string; width: number; height: number };
