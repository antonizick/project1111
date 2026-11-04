import { describe, expect, it } from "vitest";
import { composite } from "./render";

/** A 2D-context stand-in that records the compositing calls `composite` makes. */
function recorder() {
  const ops: string[] = [];
  let mode = "source-over";
  let alpha = 1;
  const ctx = {
    save: () => ops.push("save"),
    restore: () => ops.push("restore"),
    clearRect: (x: number, y: number, w: number, h: number) =>
      ops.push(`clearRect ${x},${y},${w},${h}`),
    drawImage: (src: { id: string }, ...a: number[]) =>
      ops.push(`draw ${src.id} ${mode} a=${alpha} ${a.join(",")}`),
    set globalCompositeOperation(v: string) {
      mode = v;
    },
    get globalCompositeOperation() {
      return mode;
    },
    set globalAlpha(v: number) {
      alpha = v;
    },
    get globalAlpha() {
      return alpha;
    },
  };
  return { ctx: ctx as unknown as CanvasRenderingContext2D, ops };
}

const snapshot = { id: "snapshot" } as unknown as HTMLCanvasElement;
const layer = { id: "layer" } as unknown as HTMLCanvasElement;
const rect = { x: 10, y: 20, w: 30, h: 40 };

describe("composite", () => {
  it("restores only the dirty box, never with a whole-canvas 'copy'", () => {
    const { ctx, ops } = recorder();
    composite(ctx, snapshot, layer, { tool: "brush", opacity: 0.5 }, rect);
    expect(ops).toEqual([
      "save",
      "clearRect 10,20,30,40",
      "draw snapshot source-over a=1 10,20,30,40,10,20,30,40",
      "draw layer source-over a=0.5 10,20,30,40,10,20,30,40",
      "restore",
    ]);
    expect(ops.some((o) => o.includes("copy"))).toBe(false);
  });

  it("erases the stroke layer with destination-out", () => {
    const { ctx, ops } = recorder();
    composite(ctx, snapshot, layer, { tool: "eraser", opacity: 1 }, rect);
    expect(ops[3]).toBe("draw layer destination-out a=1 10,20,30,40,10,20,30,40");
  });
});
