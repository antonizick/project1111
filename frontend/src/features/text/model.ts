// Text overlay state and geometry (Phase 14, R23). Pure: the dialog is a thin shell over this.

import type { TextOverlayStep } from "../../api/types";

export const DEFAULT_OVERLAY: TextOverlayStep = {
  type: "text_overlay",
  text: "Product Name",
  font: "sans",
  weight: "semibold",
  size_pct: 12,
  colour: "#ffffff",
  colour2: null,
  align: "center",
  position: "bottom",
  x: null,
  y: null,
  margin_pct: 6,
  letter_spacing: 0,
  stroke_px: 0,
  stroke_colour: "#000000",
  shadow: true,
  also_prompt_model: false,
};

export const POSITIONS = [
  "top-left",
  "top",
  "top-right",
  "left",
  "center",
  "right",
  "bottom-left",
  "bottom",
  "bottom-right",
] as const;

export const WEIGHTS = ["light", "regular", "medium", "semibold", "bold"] as const;

export function clamp01(n: number): number {
  return Math.min(1, Math.max(0, Number.isFinite(n) ? n : 0));
}

/** The overlay with a draggable centre: setting x/y switches off the 9-way anchor. */
export function atPoint(overlay: TextOverlayStep, x: number, y: number): TextOverlayStep {
  return { ...overlay, x: clamp01(x), y: clamp01(y) };
}

/** Where a drag from `start` by (dx, dy) pixels puts the block centre, as 0..1 fractions. */
export function draggedPoint(
  start: { x: number; y: number },
  dx: number,
  dy: number,
  size: { width: number; height: number },
): { x: number; y: number } {
  return {
    x: clamp01(start.x + (size.width ? dx / size.width : 0)),
    y: clamp01(start.y + (size.height ? dy / size.height : 0)),
  };
}

/** Turning the gradient on gives a second colour; off removes it. */
export function withGradient(overlay: TextOverlayStep, on: boolean): TextOverlayStep {
  return { ...overlay, colour2: on ? (overlay.colour2 ?? "#ffd166") : null };
}

/** The payload the API validates: trimmed text, finite numbers, no NaN from empty inputs. */
export function sanitize(overlay: TextOverlayStep): TextOverlayStep {
  const number = (v: number, fallback: number) => (Number.isFinite(v) ? v : fallback);
  return {
    ...overlay,
    text: overlay.text.trim(),
    size_pct: Math.min(100, Math.max(0.5, number(overlay.size_pct, 12))),
    margin_pct: Math.min(50, Math.max(0, number(overlay.margin_pct, 6))),
    letter_spacing: Math.min(1, Math.max(-0.2, number(overlay.letter_spacing, 0))),
    stroke_px: Math.min(64, Math.max(0, Math.round(number(overlay.stroke_px, 0)))),
    x: overlay.x === null ? null : clamp01(overlay.x),
    y: overlay.y === null ? null : clamp01(overlay.y),
  };
}

/** Whether the text is worth previewing (the API rejects an empty one). */
export function hasText(overlay: TextOverlayStep): boolean {
  return overlay.text.trim().length > 0;
}
