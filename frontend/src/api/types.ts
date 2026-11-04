// Shapes of the Studio API (docs/P11_ARCHITECTURE.md → Studio API; src/p11/api/routes/).
// Hand-written from the OpenAPI schema; only the fields the UI reads are typed.

export type JobState = "queued" | "running" | "paused" | "done" | "failed" | "cancelled";
export const FINISHED: ReadonlySet<JobState> = new Set(["done", "failed", "cancelled"]);

import type { Problem } from "./session";

export type { Problem };

export type Job = {
  id: string;
  state: JobState;
  /** "recipe" (a generation) or "video" (a video face-swap, Phase 13). */
  kind?: string;
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
  state: "installed" | "missing" | "corrupt" | "user-added" | "unregistered";
  origin: "manifest" | "user" | "disk";
  filename: string;
  path: string | null;
  size: number | null;
  sha256: string | null;
  verified: boolean;
  sets: string[];
  enabled: boolean;
  usable: boolean;
  family: string | null;
  defaults: SamplerDefaults | null;
  vae: string | null;
  format: string;
  detail: string;
  licence: {
    name: string;
    url?: string;
    commercial_use: boolean;
    flags: string[];
    accepted?: boolean;
  } | null;
};

/** One model install or add running in the service (Phase 14; ``models`` events). */
export type ModelOperation = {
  id: string;
  kind: "install" | "add" | string;
  target: string;
  state: "running" | "done" | "failed";
  label: string;
  done: number;
  total: number;
  progress: number;
  error: string | null;
  report: Record<string, unknown> | null;
  started_at: string;
  seconds: number;
};

export type ModelLicenceRow = {
  id: string;
  name: string;
  licence: string;
  url: string;
  commercial_use: boolean;
  flags: string[];
  needs_acknowledgement: boolean;
  accepted_at: string | null;
};

export type ModelPlan = {
  target: string;
  models: string[];
  to_fetch: string[];
  licences_to_accept: Omit<ModelLicenceRow, "needs_acknowledgement" | "accepted_at">[];
  total_bytes: number;
  download_bytes: number;
};

export type FontInfo = {
  id: string;
  label: string;
  weights: string[];
  licence: string;
  source: string;
};

export type TextOverlayStep = {
  type: "text_overlay";
  text: string;
  font: string;
  weight: "light" | "regular" | "medium" | "semibold" | "bold";
  size_pct: number;
  colour: string;
  colour2: string | null;
  align: "left" | "center" | "right";
  position: string;
  x: number | null;
  y: number | null;
  margin_pct: number;
  letter_spacing: number;
  stroke_px: number;
  stroke_colour: string;
  shadow: boolean;
  also_prompt_model: boolean;
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
  /** Photo edit (Phase 17b, ADR-0038): set any of these and the step starts from a photo. */
  image_slot?: string | null;
  denoise?: number | null;
  denoise_preset?: PhotoPreset | null;
};

export type PhotoPreset = "light" | "change" | "reimagine";

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

export type Upload = {
  id: string;
  kind: string;
  width: number;
  height: number;
  sha256?: string;
  created_at?: string;
  /** Videos only: length in seconds and the R13 limit warnings. */
  seconds?: number | null;
  warnings?: string[];
};

/** A video face-swap job with its pipeline detail (Phase 13). */
export type VideoJob = Job & {
  record_job: string;
  stage: string;
  frames: number;
  swapped: number;
  pass_through: number;
  seconds: number;
  fps: number;
  width: number;
  height: number;
  timings: Record<string, number>;
  resumable: boolean;
  file: string | null;
};

/** What one video face-swap run does (`POST /api/video/jobs`). */
export type VideoRequest = {
  video: string;
  face: string;
  quality?: "fast" | "good";
  source_face_index?: number;
  /** Face picked on the first frame; `null` = largest face in every frame. */
  target_face?: number | null;
  trim_start?: number;
  trim_end?: number | null;
  max_height?: number | null;
  smooth?: boolean;
  keep_frames?: boolean;
  confirm_limits?: boolean;
};
