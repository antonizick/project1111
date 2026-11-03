// Pure parts of the mask editor: the edit history (undo/redo), brush geometry, view transform and
// key bindings. The canvas side (MaskEditor.tsx) replays the history onto an image-sized canvas.

export type Tool = "brush" | "eraser";

export type Point = { x: number; y: number; pressure: number };

export type Stroke = {
  type: "stroke";
  tool: Tool;
  /** Diameter in image pixels at pressure 1. */
  size: number;
  /** 0 = soft edge, 1 = hard edge. */
  hardness: number;
  /** 0..1, applied to the whole stroke (overlapping dabs do not build up). */
  opacity: number;
  points: Point[];
};

export type Op = Stroke | { type: "clear" } | { type: "invert" };

export type History = { done: Op[]; undone: Op[] };

export const EMPTY: History = { done: [], undone: [] };
export const MAX_HISTORY = 200;

/** A new op: becomes the last done op and clears redo. */
export function push(h: History, op: Op): History {
  const done = [...h.done, op];
  return { done: done.length > MAX_HISTORY ? done.slice(-MAX_HISTORY) : done, undone: [] };
}

export function undo(h: History): History {
  const op = h.done[h.done.length - 1];
  if (!op) return h;
  return { done: h.done.slice(0, -1), undone: [...h.undone, op] };
}

export function redo(h: History): History {
  const op = h.undone[h.undone.length - 1];
  if (!op) return h;
  return { done: [...h.done, op], undone: h.undone.slice(0, -1) };
}

export const canUndo = (h: History): boolean => h.done.length > 0;
export const canRedo = (h: History): boolean => h.undone.length > 0;

/** The ops that matter for drawing: everything after the last clear. */
export function visibleOps(h: History): Op[] {
  for (let i = h.done.length - 1; i >= 0; i--)
    if (h.done[i]?.type === "clear") return h.done.slice(i + 1);
  return h.done;
}

/** Cheap "is there a mask" for enabling Apply; export checks the pixels exactly. */
export function hasMask(h: History): boolean {
  return visibleOps(h).some(
    (o) => o.type === "invert" || (o.type === "stroke" && o.tool === "brush" && o.opacity > 0),
  );
}

// --- brush ---------------------------------------------------------------------------------

export const MIN_SIZE = 2;
export const MAX_SIZE = 600;

/** `[` and `]`: about 15 % per press, at least 2 px. */
export function stepSize(size: number, dir: 1 | -1): number {
  const delta = Math.max(2, Math.round(size * 0.15));
  return Math.min(MAX_SIZE, Math.max(MIN_SIZE, size + dir * delta));
}

/** Pen pressure scales the brush; mouse and touch report fixed values, so they count as 1. */
export function pressureOf(pointerType: string, pressure: number): number {
  if (pointerType !== "pen") return 1;
  return Math.min(1, Math.max(0.1, pressure || 0.5));
}

/** Dab centres from `a` to `b` spaced by a fraction of the brush, so fast strokes stay solid. */
export function interpolate(a: Point, b: Point, size: number, spacing = 0.15): Point[] {
  const dist = Math.hypot(b.x - a.x, b.y - a.y);
  const step = Math.max(0.5, size * spacing * Math.min(a.pressure, b.pressure));
  const n = Math.max(1, Math.ceil(dist / step));
  const out: Point[] = [];
  for (let i = 1; i <= n; i++) {
    const t = i / n;
    out.push({
      x: a.x + (b.x - a.x) * t,
      y: a.y + (b.y - a.y) * t,
      pressure: a.pressure + (b.pressure - a.pressure) * t,
    });
  }
  return out;
}

/** Bounding box of a stroke in image pixels (for partial redraws). */
export function strokeBounds(s: Stroke): { x: number; y: number; w: number; h: number } {
  const r = s.size / 2 + 2;
  let x0 = Infinity;
  let y0 = Infinity;
  let x1 = -Infinity;
  let y1 = -Infinity;
  for (const p of s.points) {
    x0 = Math.min(x0, p.x - r);
    y0 = Math.min(y0, p.y - r);
    x1 = Math.max(x1, p.x + r);
    y1 = Math.max(y1, p.y + r);
  }
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}

// --- view ----------------------------------------------------------------------------------

/** Image → screen: screen = offset + image * scale. */
export type View = { scale: number; x: number; y: number };
export const MAX_ZOOM = 16;

/** The view that fits an image of `w`×`h` into a box of `bw`×`bh`, centred. */
export function fit(w: number, h: number, bw: number, bh: number): View {
  const scale = Math.min(bw / w, bh / h) || 1;
  return { scale, x: (bw - w * scale) / 2, y: (bh - h * scale) / 2 };
}

/** Zoom by `factor` around the screen point (px, py), between `min` and MAX_ZOOM. */
export function zoomAround(v: View, factor: number, px: number, py: number, min: number): View {
  const scale = Math.min(MAX_ZOOM, Math.max(min, v.scale * factor));
  const k = scale / v.scale;
  return { scale, x: px - (px - v.x) * k, y: py - (py - v.y) * k };
}

export function toImage(v: View, sx: number, sy: number): { x: number; y: number } {
  return { x: (sx - v.x) / v.scale, y: (sy - v.y) / v.scale };
}

// --- keys ----------------------------------------------------------------------------------

export type EditorCommand =
  "undo" | "redo" | "smaller" | "bigger" | "brush" | "eraser" | "toggleMask" | "invert";

type KeyLike = Pick<KeyboardEvent, "key" | "ctrlKey" | "metaKey" | "shiftKey" | "altKey">;

export function editorCommand(e: KeyLike): EditorCommand | null {
  const mod = e.ctrlKey || e.metaKey;
  const k = e.key.toLowerCase();
  if (mod && !e.altKey && k === "z") return e.shiftKey ? "redo" : "undo";
  if (mod && !e.altKey && k === "y") return "redo";
  if (mod || e.altKey) return null;
  switch (e.key) {
    case "[":
      return "smaller";
    case "]":
      return "bigger";
  }
  switch (k) {
    case "b":
      return "brush";
    case "e":
      return "eraser";
    case "h":
      return "toggleMask";
    case "i":
      return "invert";
  }
  return null;
}
