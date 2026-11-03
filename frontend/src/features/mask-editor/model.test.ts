import { describe, expect, it } from "vitest";
import {
  EMPTY,
  MAX_HISTORY,
  MAX_SIZE,
  MIN_SIZE,
  canRedo,
  canUndo,
  editorCommand,
  fit,
  hasMask,
  interpolate,
  pressureOf,
  push,
  redo,
  stepSize,
  strokeBounds,
  toImage,
  undo,
  visibleOps,
  zoomAround,
  type Stroke,
} from "./model";

const stroke = (tool: Stroke["tool"] = "brush", opacity = 1): Stroke => ({
  type: "stroke",
  tool,
  size: 20,
  hardness: 1,
  opacity,
  points: [{ x: 10, y: 10, pressure: 1 }],
});

describe("history", () => {
  it("undoes and redoes in order and a new op clears redo", () => {
    const a = stroke();
    const b = stroke("eraser");
    let h = push(push(EMPTY, a), b);
    expect(h.done).toEqual([a, b]);
    h = undo(h);
    expect(h.done).toEqual([a]);
    expect(canRedo(h)).toBe(true);
    h = redo(h);
    expect(h.done).toEqual([a, b]);
    h = push(undo(h), { type: "invert" });
    expect(h.undone).toEqual([]);
    expect(canRedo(h)).toBe(false);
    expect(undo(EMPTY)).toBe(EMPTY);
    expect(redo(EMPTY)).toBe(EMPTY);
    expect(canUndo(EMPTY)).toBe(false);
  });

  it("caps the history length", () => {
    let h = EMPTY;
    for (let i = 0; i < MAX_HISTORY + 10; i++) h = push(h, stroke());
    expect(h.done).toHaveLength(MAX_HISTORY);
  });

  it("clear hides earlier ops and undoing it brings them back", () => {
    const a = stroke();
    const h = push(push(EMPTY, a), { type: "clear" });
    expect(visibleOps(h)).toEqual([]);
    expect(hasMask(h)).toBe(false);
    expect(visibleOps(undo(h))).toEqual([a]);
    expect(hasMask(undo(h))).toBe(true);
  });

  it("knows when nothing is painted", () => {
    expect(hasMask(EMPTY)).toBe(false);
    expect(hasMask(push(EMPTY, stroke("eraser")))).toBe(false);
    expect(hasMask(push(EMPTY, { type: "invert" }))).toBe(true);
  });
});

describe("brush", () => {
  it("steps the size with [ and ] within bounds", () => {
    expect(stepSize(100, 1)).toBe(115);
    expect(stepSize(100, -1)).toBe(85);
    expect(stepSize(MIN_SIZE, -1)).toBe(MIN_SIZE);
    expect(stepSize(MAX_SIZE, 1)).toBe(MAX_SIZE);
    expect(stepSize(4, 1)).toBe(6);
  });

  it("uses pen pressure only for pens", () => {
    expect(pressureOf("mouse", 0.5)).toBe(1);
    expect(pressureOf("touch", 0)).toBe(1);
    expect(pressureOf("pen", 0.3)).toBe(0.3);
    expect(pressureOf("pen", 0)).toBe(0.5);
    expect(pressureOf("pen", 0.01)).toBe(0.1);
  });

  it("fills fast strokes with evenly spaced dabs", () => {
    const pts = interpolate({ x: 0, y: 0, pressure: 1 }, { x: 100, y: 0, pressure: 1 }, 20);
    expect(pts).toHaveLength(34);
    expect(pts.at(-1)).toEqual({ x: 100, y: 0, pressure: 1 });
    const gaps = pts.slice(1).map((p, i) => p.x - pts[i]!.x);
    expect(Math.max(...gaps)).toBeLessThanOrEqual(3);
    expect(interpolate({ x: 5, y: 5, pressure: 1 }, { x: 5, y: 5, pressure: 1 }, 20)).toHaveLength(
      1,
    );
  });

  it("bounds a stroke by its radius", () => {
    expect(strokeBounds(stroke())).toEqual({ x: -2, y: -2, w: 24, h: 24 });
  });
});

describe("view", () => {
  it("fits and centres the image", () => {
    expect(fit(2560, 1440, 1280, 1000)).toEqual({ scale: 0.5, x: 0, y: 140 });
  });

  it("zooms around the cursor and keeps that image point under it", () => {
    const v = { scale: 0.5, x: 0, y: 140 };
    const before = toImage(v, 300, 200);
    const z = zoomAround(v, 2, 300, 200, 0.25);
    expect(z.scale).toBe(1);
    const after = toImage(z, 300, 200);
    expect(after.x).toBeCloseTo(before.x);
    expect(after.y).toBeCloseTo(before.y);
    expect(zoomAround(v, 0.01, 0, 0, 0.25).scale).toBe(0.25);
    expect(zoomAround(v, 1000, 0, 0, 0.25).scale).toBe(16);
  });
});

describe("keys", () => {
  const k = (key: string, mods: Partial<KeyboardEvent> = {}) =>
    editorCommand({ key, ctrlKey: false, metaKey: false, shiftKey: false, altKey: false, ...mods });
  it("maps the editor shortcuts", () => {
    expect(k("z", { ctrlKey: true })).toBe("undo");
    expect(k("Z", { ctrlKey: true, shiftKey: true })).toBe("redo");
    expect(k("y", { metaKey: true })).toBe("redo");
    expect(k("[")).toBe("smaller");
    expect(k("]")).toBe("bigger");
    expect(k("b")).toBe("brush");
    expect(k("E")).toBe("eraser");
    expect(k("h")).toBe("toggleMask");
    expect(k("i")).toBe("invert");
    expect(k("b", { ctrlKey: true })).toBeNull();
    expect(k("x")).toBeNull();
  });
});

describe("seed entries (Phase 11 initialMask)", () => {
  const seedOp = { type: "seed", image: document.createElement("canvas") } as const;

  it("counts as a mask until it is undone or cleared", () => {
    const seeded = push(EMPTY, seedOp);
    expect(hasMask(seeded)).toBe(true);
    expect(hasMask(undo(seeded))).toBe(false);
    expect(hasMask(push(seeded, { type: "clear" }))).toBe(false);
  });

  it("is the base the strokes draw on: visible until a clear", () => {
    const h = push(push(EMPTY, seedOp), { type: "clear" });
    expect(visibleOps(h)).toHaveLength(0);
    expect(visibleOps(push(EMPTY, seedOp))).toHaveLength(1);
  });
});
