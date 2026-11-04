// Canvas side of the mask editor: dabs, stroke compositing, replay, invert and PNG export.
// The mask canvas is image-sized; its alpha is the mask (the colour is only for display).

import { visibleOps, type History, type Point, type Stroke } from "./model";

export const MASK_COLOUR = "rgb(255, 48, 96)";

export type Rect = { x: number; y: number; w: number; h: number };

type Ctx = CanvasRenderingContext2D;

export function ctx2d(canvas: HTMLCanvasElement): Ctx | null {
  return canvas.getContext("2d", { willReadFrequently: false });
}

/** One round dab of the brush at `p`; soft edges use a radial gradient. */
export function dab(c: Ctx, p: Point, size: number, hardness: number): void {
  const r = Math.max(0.5, (size * p.pressure) / 2);
  c.beginPath();
  c.arc(p.x, p.y, r, 0, Math.PI * 2);
  if (hardness >= 0.99) {
    c.fillStyle = MASK_COLOUR;
  } else {
    const g = c.createRadialGradient(p.x, p.y, r * hardness, p.x, p.y, r);
    g.addColorStop(0, MASK_COLOUR);
    g.addColorStop(1, "rgba(255, 48, 96, 0)");
    c.fillStyle = g;
  }
  c.fill();
}

/** Grow `rect` to whole pixels inside a `w`×`h` canvas; null if it misses the canvas. */
export function clampRect(rect: Rect, w: number, h: number): Rect | null {
  const x = Math.max(0, Math.floor(rect.x));
  const y = Math.max(0, Math.floor(rect.y));
  const x1 = Math.min(w, Math.ceil(rect.x + rect.w));
  const y1 = Math.min(h, Math.ceil(rect.y + rect.h));
  return x1 > x && y1 > y ? { x, y, w: x1 - x, h: y1 - y } : null;
}

export function union(a: Rect | null, b: Rect): Rect {
  if (!a) return b;
  const x = Math.min(a.x, b.x);
  const y = Math.min(a.y, b.y);
  return {
    x,
    y,
    w: Math.max(a.x + a.w, b.x + b.w) - x,
    h: Math.max(a.y + a.h, b.y + b.h) - y,
  };
}

/**
 * Within `rect`: mask = snapshot, then the stroke layer at the stroke's opacity, painted
 * (source-over) or erased (destination-out). Used live while drawing and for replay.
 * The box is restored with clearRect + source-over, not "copy": a "copy" draw clears the whole
 * canvas outside the drawn image, which wiped the stroke behind each live dab box (Phase 17a).
 */
export function composite(
  mask: Ctx,
  snapshot: HTMLCanvasElement,
  layer: HTMLCanvasElement,
  stroke: Pick<Stroke, "tool" | "opacity">,
  rect: Rect,
): void {
  const { x, y, w, h } = rect;
  mask.save();
  mask.clearRect(x, y, w, h);
  mask.globalCompositeOperation = "source-over";
  mask.drawImage(snapshot, x, y, w, h, x, y, w, h);
  mask.globalCompositeOperation = stroke.tool === "brush" ? "source-over" : "destination-out";
  mask.globalAlpha = stroke.opacity;
  mask.drawImage(layer, x, y, w, h, x, y, w, h);
  mask.restore();
}

export function invert(mask: Ctx, scratch: HTMLCanvasElement): void {
  const { width: w, height: h } = mask.canvas;
  const s = ctx2d(scratch);
  if (!s) return;
  s.save();
  s.globalCompositeOperation = "copy";
  s.fillStyle = MASK_COLOUR;
  s.fillRect(0, 0, w, h);
  s.globalCompositeOperation = "destination-out";
  s.drawImage(mask.canvas, 0, 0);
  s.restore();
  mask.save();
  mask.globalCompositeOperation = "copy";
  mask.drawImage(scratch, 0, 0);
  mask.restore();
}

export function drawStrokeLayer(layer: Ctx, s: Stroke): void {
  layer.clearRect(0, 0, layer.canvas.width, layer.canvas.height);
  for (const p of s.points) dab(layer, p, s.size, s.hardness);
}

/** Redraw the whole mask from the history (after undo/redo or a reset). */
export function replay(
  mask: Ctx,
  history: History,
  snapshot: HTMLCanvasElement,
  layer: HTMLCanvasElement,
): void {
  const { width: w, height: h } = mask.canvas;
  mask.clearRect(0, 0, w, h);
  const lc = ctx2d(layer);
  const sc = ctx2d(snapshot);
  if (!lc || !sc) return;
  const full = { x: 0, y: 0, w, h };
  for (const op of visibleOps(history)) {
    if (op.type === "seed") mask.drawImage(op.image, 0, 0);
    else if (op.type === "invert") invert(mask, snapshot);
    else if (op.type === "stroke") {
      sc.clearRect(0, 0, w, h);
      sc.drawImage(mask.canvas, 0, 0);
      drawStrokeLayer(lc, op);
      composite(mask, snapshot, layer, op, full);
    }
  }
  lc.clearRect(0, 0, w, h);
}

/**
 * A greyscale mask image (white = painted, from the server's auto-mask) as an alpha-mask canvas
 * in the editor's display colour, so it can be the history's seed entry.
 */
export function seedCanvas(img: CanvasImageSource, w: number, h: number): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  const s = ctx2d(c);
  if (!s) return c;
  s.drawImage(img, 0, 0, w, h);
  const data = s.getImageData(0, 0, w, h);
  const p = data.data;
  for (let i = 0; i < p.length; i += 4) {
    const a = Math.round((p[i]! * p[i + 3]!) / 255);
    p[i] = 255;
    p[i + 1] = 48;
    p[i + 2] = 96;
    p[i + 3] = a;
  }
  s.putImageData(data, 0, 0);
  return c;
}

/** True if any pixel of the mask is painted (alpha > 0). */
export function painted(mask: Ctx): boolean {
  const { width: w, height: h } = mask.canvas;
  const data = mask.getImageData(0, 0, w, h).data;
  for (let i = 3; i < data.length; i += 4) if (data[i]! > 0) return true;
  return false;
}

/** The mask as a greyscale PNG at image resolution (white = repaint), or null when empty. */
export async function exportMask(mask: Ctx): Promise<Blob | null> {
  if (!painted(mask)) return null;
  const { width: w, height: h } = mask.canvas;
  const out = document.createElement("canvas");
  out.width = w;
  out.height = h;
  const white = document.createElement("canvas");
  white.width = w;
  white.height = h;
  const o = ctx2d(out);
  const wc = ctx2d(white);
  if (!o || !wc) return null;
  wc.fillStyle = "#fff";
  wc.fillRect(0, 0, w, h);
  wc.globalCompositeOperation = "destination-in";
  wc.drawImage(mask.canvas, 0, 0);
  o.fillStyle = "#000";
  o.fillRect(0, 0, w, h);
  o.drawImage(white, 0, 0);
  return new Promise((resolve) => out.toBlob((b) => resolve(b), "image/png"));
}
