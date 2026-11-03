// Face & Pose form state → recipe JSON (schema v1, src/p11/recipe/model.py). Pure: the ID and the
// clock are passed in. The four tools are four recipes: swap a face onto a picture, restore the
// faces of a picture, generate following a pose, generate in the style of a reference image.

import type { Recipe, SeedStrategy, SlotKind } from "../../api/types";
import { MAX_SEED, recipeName } from "../generate/form";

export const FACE_SLOT = "face";
export const POSE_SLOT = "pose";
export const REFERENCE_SLOT = "reference";

export type Built = { recipe: Recipe; bindings: Record<string, unknown> };

export type SwapForm = {
  targetRef: string;
  faceRef: string;
  sourceFaceIndex: number;
  targetFaceIndex: number;
  blend: number;
  restore: boolean;
  restoreVisibility: number;
};

export type RestoreForm = {
  targetRef: string;
  faceIndex: number | null;
  visibility: number;
};

export type ControlKind = "openpose" | "depth" | "canny";

export type PoseForm = {
  prompt: string;
  style: string;
  aspect: string | null;
  /** The pose slot's picture: a photo to read, or the pose editor's rendering. */
  poseRef: string;
  preprocess: boolean;
  control: ControlKind;
  strength: number;
  start: number;
  end: number;
};

export type ReferenceMode = "style" | "character";

export type ReferenceForm = {
  prompt: string;
  style: string;
  aspect: string | null;
  referenceRef: string;
  mode: ReferenceMode;
  weight: number;
  start: number;
  end: number;
};

function seed(seedValue: number | null): SeedStrategy {
  return seedValue === null
    ? { kind: "random" }
    : { kind: "fixed", value: Math.min(MAX_SEED, Math.max(0, Math.round(seedValue))) };
}

function generateStep(prompt: string, style: string, aspect: string | null) {
  return {
    type: "generate",
    prompt: prompt.trim(),
    negative: "",
    style,
    aspect,
    model: null,
    loras: [],
    sampler: null,
    chain: null,
    quality: false,
    batch_size: 1,
  };
}

function slot(name: string, kind: SlotKind, label: string) {
  return { name, kind, label, required: true, default: null };
}

export function swapRecipe(
  form: SwapForm,
  { id, now, seedValue = null }: { id: string; now: Date; seedValue?: number | null },
): Built {
  return {
    recipe: {
      schema_version: 1,
      id,
      name: recipeName("Swap face"),
      tags: [],
      folder: "",
      steps: [
        {
          type: "face_swap",
          face_slot: FACE_SLOT,
          image_slot: null,
          source_face_index: form.sourceFaceIndex,
          target_face_index: form.targetFaceIndex,
          swapper_model: null,
          blend: form.blend,
          restore: form.restore,
          restore_model: null,
          restore_visibility: form.restoreVisibility,
        },
      ],
      slots: [slot(FACE_SLOT, "face_image", "Face photo")],
      seed: seed(seedValue),
      created_at: now.toISOString(),
      source_image: { ref: form.targetRef },
    },
    bindings: { [FACE_SLOT]: { ref: form.faceRef } },
  };
}

export function restoreRecipe(form: RestoreForm, { id, now }: { id: string; now: Date }): Built {
  return {
    recipe: {
      schema_version: 1,
      id,
      name: recipeName("Restore faces"),
      tags: [],
      folder: "",
      steps: [
        {
          type: "face_restore",
          image_slot: null,
          face_index: form.faceIndex,
          restore_model: null,
          visibility: form.visibility,
        },
      ],
      slots: [],
      seed: seed(null),
      created_at: now.toISOString(),
      source_image: { ref: form.targetRef },
    },
    bindings: {},
  };
}

export function poseRecipe(
  form: PoseForm,
  { id, now, seedValue = null }: { id: string; now: Date; seedValue?: number | null },
): Built {
  return {
    recipe: {
      schema_version: 1,
      id,
      name: recipeName(form.prompt || "Pose"),
      tags: [],
      folder: "",
      steps: [
        generateStep(form.prompt, form.style, form.aspect),
        {
          type: "pose",
          pose_slot: POSE_SLOT,
          preprocess: form.preprocess,
          control: form.control,
          controlnet: null,
          strength: form.strength,
          start: form.start,
          end: form.end,
        },
      ],
      slots: [slot(POSE_SLOT, "image", "Pose")],
      seed: seed(seedValue),
      created_at: now.toISOString(),
      source_image: null,
    },
    bindings: { [POSE_SLOT]: { ref: form.poseRef } },
  };
}

export function referenceRecipe(
  form: ReferenceForm,
  { id, now, seedValue = null }: { id: string; now: Date; seedValue?: number | null },
): Built {
  return {
    recipe: {
      schema_version: 1,
      id,
      name: recipeName(form.prompt || "Reference"),
      tags: [],
      folder: "",
      steps: [
        generateStep(form.prompt, form.style, form.aspect),
        {
          type: "reference",
          image_slot: REFERENCE_SLOT,
          mode: form.mode,
          ipadapter: null,
          weight: form.weight,
          start: form.start,
          end: form.end,
        },
      ],
      slots: [slot(REFERENCE_SLOT, "image", "Reference image")],
      seed: seed(seedValue),
      created_at: now.toISOString(),
      source_image: null,
    },
    bindings: { [REFERENCE_SLOT]: { ref: form.referenceRef } },
  };
}

export const CONSENT_NOTICE = "Use faces of people who agreed.";
