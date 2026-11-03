// Recipe builders for the Phase 14 follow-ups: text overlay on an image, and logo exports.

import type { Recipe, TextOverlayStep } from "../../api/types";
import { recipeName } from "../generate/form";
import { sanitize } from "./model";

/** The gallery image with exact text drawn on it (a text_overlay-only edit). */
export function textOverlayRecipe(
  imageId: number,
  prompt: string,
  overlay: TextOverlayStep,
  { id, now }: { id: string; now: Date },
): Recipe {
  return {
    schema_version: 1,
    id,
    name: recipeName(`Text: ${overlay.text || prompt}`),
    tags: [],
    folder: "",
    steps: [sanitize(overlay)],
    slots: [],
    seed: { kind: "random" },
    created_at: now.toISOString(),
    source_image: { ref: `gallery/${imageId}` },
  };
}
