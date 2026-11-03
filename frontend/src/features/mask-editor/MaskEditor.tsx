// The mask editor (Phase 10, reused by background and face regions): paint where the image should
// change. Brush/eraser with size, hardness and opacity, feather preview, invert, clear, undo/redo,
// wheel zoom and space/middle-drag pan, pen pressure. The mask canvas is image-sized and sits
// under a CSS transform, so zoom and pan never redraw it; a stroke only recomposites its dirty box.
// Give it a `key` per image: a new image starts a new mask.

import { useCallback, useEffect, useImperativeHandle, useRef, useState, type Ref } from "react";
import { isTyping } from "../../app/shortcuts";
import {
  EMPTY,
  canRedo,
  canUndo,
  editorCommand,
  fit,
  hasMask,
  interpolate,
  MAX_SIZE,
  MIN_SIZE,
  pressureOf,
  push,
  redo,
  stepSize,
  toImage,
  undo,
  zoomAround,
  type History,
  type Point,
  type Stroke,
  type Tool,
  type View,
} from "./model";
import {
  clampRect,
  composite,
  ctx2d,
  dab,
  exportMask,
  invert as invertMask,
  replay,
  union,
  type Rect,
} from "./render";

export type MaskEditorHandle = {
  /** Greyscale PNG at image resolution, or null when nothing is painted. */
  exportMask: () => Promise<Blob | null>;
  clear: () => void;
  /** Draw timing of the strokes so far (ms per pointer move), for the 60 fps check. */
  stats: () => { moves: number; avgMs: number; maxMs: number };
};

type Drag =
  | { kind: "draw"; stroke: Stroke; last: Point; dirty: Rect | null }
  | { kind: "pan"; sx: number; sy: number; vx: number; vy: number };

export function MaskEditor({
  src,
  width,
  height,
  feather,
  onFeather,
  onChange,
  active = true,
  ref,
}: {
  src: string;
  width: number;
  height: number;
  /** Mask blur in image pixels (previewed here, applied by the server). */
  feather: number;
  onFeather: (px: number) => void;
  onChange?: (hasMask: boolean) => void;
  /** Keyboard shortcuts are live only while the editor's view is shown. */
  active?: boolean;
  ref?: Ref<MaskEditorHandle>;
}) {
  const [tool, setTool] = useState<Tool>("brush");
  const [size, setSize] = useState(() => Math.max(8, Math.round(Math.max(width, height) / 25)));
  const [hardness, setHardness] = useState(0.7);
  const [opacity, setOpacity] = useState(1);
  const [showMask, setShowMask] = useState(true);
  const [history, setHistory] = useState<History>(EMPTY);
  const [view, setView] = useState<View>({ scale: 1, x: 0, y: 0 });
  const [minScale, setMinScale] = useState(0.1);
  const [panning, setPanning] = useState(false);

  const stage = useRef<HTMLDivElement>(null);
  const mask = useRef<HTMLCanvasElement>(null);
  const cursor = useRef<HTMLDivElement>(null);
  const snapshot = useRef<HTMLCanvasElement | null>(null);
  const layer = useRef<HTMLCanvasElement | null>(null);
  const drag = useRef<Drag | null>(null);
  const space = useRef(false);
  const timing = useRef({ moves: 0, total: 0, max: 0 });
  const latest = useRef({ view, minScale });
  useEffect(() => {
    latest.current = { view, minScale };
  });

  const offscreen = useCallback(() => {
    const make = () => {
      const c = document.createElement("canvas");
      c.width = width;
      c.height = height;
      return c;
    };
    if (!snapshot.current || snapshot.current.width !== width) snapshot.current = make();
    if (!layer.current || layer.current.width !== width) layer.current = make();
    return { snap: snapshot.current, lay: layer.current };
  }, [width, height]);

  // Fit the image into the stage when it (or the stage) changes size.
  useEffect(() => {
    const el = stage.current;
    if (!el) return;
    const refit = () => {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) return;
      const v = fit(width, height, r.width, r.height);
      setView(v);
      setMinScale(v.scale * 0.5);
    };
    refit();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(refit);
    ro.observe(el);
    return () => ro.disconnect();
  }, [width, height, src]);

  const apply = useCallback(
    (next: History, redraw: boolean) => {
      setHistory(next);
      onChange?.(hasMask(next));
      const c = mask.current && ctx2d(mask.current);
      if (redraw && c) {
        const { snap, lay } = offscreen();
        replay(c, next, snap, lay);
      }
    },
    [onChange, offscreen],
  );

  const doUndo = useCallback(
    () => canUndo(history) && apply(undo(history), true),
    [history, apply],
  );
  const doRedo = useCallback(
    () => canRedo(history) && apply(redo(history), true),
    [history, apply],
  );
  const doClear = useCallback(() => {
    if (!hasMask(history) && history.done.length === 0) return;
    apply(push(history, { type: "clear" }), true);
  }, [history, apply]);
  const doInvert = useCallback(() => {
    const c = mask.current && ctx2d(mask.current);
    if (!c) return;
    invertMask(c, offscreen().snap);
    apply(push(history, { type: "invert" }), false);
  }, [history, apply, offscreen]);

  useImperativeHandle(
    ref,
    () => ({
      exportMask: async () => {
        const c = mask.current && ctx2d(mask.current);
        return c ? exportMask(c) : null;
      },
      clear: doClear,
      stats: () => {
        const t = timing.current;
        return { moves: t.moves, avgMs: t.moves ? t.total / t.moves : 0, maxMs: t.max };
      },
    }),
    [doClear],
  );

  // Shortcuts: [ ] size, B/E tools, H show/hide, I invert, Ctrl+Z / Ctrl+Shift+Z; space pans.
  useEffect(() => {
    if (!active) return;
    const down = (e: KeyboardEvent) => {
      if (isTyping(e.target)) return;
      if (e.key === " ") {
        space.current = true;
        setPanning(true);
        e.preventDefault();
        return;
      }
      const cmd = editorCommand(e);
      if (!cmd) return;
      e.preventDefault();
      if (cmd === "undo") doUndo();
      else if (cmd === "redo") doRedo();
      else if (cmd === "smaller") setSize((s) => stepSize(s, -1));
      else if (cmd === "bigger") setSize((s) => stepSize(s, 1));
      else if (cmd === "brush" || cmd === "eraser") setTool(cmd);
      else if (cmd === "toggleMask") setShowMask((v) => !v);
      else if (cmd === "invert") doInvert();
    };
    const up = (e: KeyboardEvent) => {
      if (e.key === " ") {
        space.current = false;
        setPanning(false);
      }
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, [active, doUndo, doRedo, doInvert]);

  // Wheel / pinch zoom at the cursor (non-passive so the page does not scroll).
  useEffect(() => {
    const el = stage.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const { view: v, minScale: min } = latest.current;
      const factor = Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015));
      setView(zoomAround(v, factor, e.clientX - r.left, e.clientY - r.top, min));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const local = (e: { clientX: number; clientY: number }) => {
    const r = stage.current!.getBoundingClientRect();
    return { sx: e.clientX - r.left, sy: e.clientY - r.top };
  };

  const moveCursor = (sx: number, sy: number) => {
    const el = cursor.current;
    if (!el) return;
    const d = size * view.scale;
    el.style.transform = `translate(${sx - d / 2}px, ${sy - d / 2}px)`;
    el.style.width = el.style.height = `${d}px`;
  };

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button === 2) return;
    const { sx, sy } = local(e);
    e.currentTarget.setPointerCapture?.(e.pointerId);
    if (e.button === 1 || space.current) {
      drag.current = { kind: "pan", sx, sy, vx: view.x, vy: view.y };
      setPanning(true);
      return;
    }
    const c = mask.current && ctx2d(mask.current);
    if (!c) return;
    const { snap, lay } = offscreen();
    const sc = ctx2d(snap);
    const lc = ctx2d(lay);
    if (!sc || !lc) return;
    sc.clearRect(0, 0, width, height);
    sc.drawImage(mask.current!, 0, 0);
    lc.clearRect(0, 0, width, height);
    const { x, y } = toImage(view, sx, sy);
    const p = { x, y, pressure: pressureOf(e.pointerType, e.pressure) };
    const stroke: Stroke = { type: "stroke", tool, size, hardness, opacity, points: [p] };
    drag.current = { kind: "draw", stroke, last: p, dirty: null };
    paint([p]);
  };

  /** Draw dabs for `points` onto the stroke layer and recomposite their box into the mask. */
  const paint = (points: Point[]) => {
    const d = drag.current;
    const c = mask.current && ctx2d(mask.current);
    if (!d || d.kind !== "draw" || !c || !layer.current || !snapshot.current) return;
    const t0 = performance.now();
    const lc = ctx2d(layer.current);
    if (!lc) return;
    const r = d.stroke.size / 2 + 2;
    let box: Rect | null = null;
    for (const p of points) {
      dab(lc, p, d.stroke.size, d.stroke.hardness);
      box = union(box, { x: p.x - r, y: p.y - r, w: 2 * r, h: 2 * r });
    }
    const rect = box && clampRect(box, width, height);
    if (rect) composite(c, snapshot.current, layer.current, d.stroke, rect);
    const ms = performance.now() - t0;
    const t = timing.current;
    t.moves += 1;
    t.total += ms;
    t.max = Math.max(t.max, ms);
  };

  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const { sx, sy } = local(e);
    moveCursor(sx, sy);
    const d = drag.current;
    if (!d) return;
    if (d.kind === "pan") {
      setView({ ...view, x: d.vx + sx - d.sx, y: d.vy + sy - d.sy });
      return;
    }
    const events = e.nativeEvent.getCoalescedEvents?.() ?? [];
    const samples = events.length ? events : [e.nativeEvent];
    const out: Point[] = [];
    let last = d.last;
    for (const ev of samples) {
      const { sx: ex, sy: ey } = local(ev);
      const { x, y } = toImage(view, ex, ey);
      const p = { x, y, pressure: pressureOf(ev.pointerType, ev.pressure) };
      out.push(...interpolate(last, p, d.stroke.size));
      last = p;
    }
    d.stroke.points.push(...out);
    d.last = last;
    paint(out);
  };

  const onPointerUp = () => {
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    if (d.kind === "pan") {
      setPanning(space.current);
      return;
    }
    apply(push(history, d.stroke), false);
    // Draw cost so far, readable by the e2e frame-timing check (no re-render).
    const t = timing.current;
    if (stage.current && t.moves) {
      stage.current.dataset.drawAvgMs = (t.total / t.moves).toFixed(3);
      stage.current.dataset.drawMaxMs = t.max.toFixed(3);
      stage.current.dataset.drawMoves = String(t.moves);
    }
  };

  const pct = Math.round(view.scale * 100);
  return (
    <div className="mask-editor">
      <div className="mask-toolbar" role="toolbar" aria-label="Mask tools">
        <div className="chips" role="group" aria-label="Tool">
          <button
            type="button"
            className="chip"
            aria-pressed={tool === "brush"}
            onClick={() => setTool("brush")}
          >
            Brush <kbd>B</kbd>
          </button>
          <button
            type="button"
            className="chip"
            aria-pressed={tool === "eraser"}
            onClick={() => setTool("eraser")}
          >
            Eraser <kbd>E</kbd>
          </button>
        </div>
        <label className="slider">
          <span>
            Size {size} px <kbd>[</kbd> <kbd>]</kbd>
          </span>
          <input
            type="range"
            min={MIN_SIZE}
            max={MAX_SIZE}
            value={size}
            onChange={(e) => setSize(Number(e.target.value))}
          />
        </label>
        <label className="slider">
          <span>Hardness {Math.round(hardness * 100)} %</span>
          <input
            type="range"
            min={0}
            max={100}
            value={Math.round(hardness * 100)}
            onChange={(e) => setHardness(Number(e.target.value) / 100)}
          />
        </label>
        <label className="slider">
          <span>Opacity {Math.round(opacity * 100)} %</span>
          <input
            type="range"
            min={5}
            max={100}
            value={Math.round(opacity * 100)}
            onChange={(e) => setOpacity(Number(e.target.value) / 100)}
          />
        </label>
        <label className="slider">
          <span>Feather {feather} px</span>
          <input
            type="range"
            min={0}
            max={128}
            value={feather}
            onChange={(e) => onFeather(Number(e.target.value))}
          />
        </label>
        <div className="row" role="group" aria-label="Mask actions">
          <button type="button" className="btn" disabled={!canUndo(history)} onClick={doUndo}>
            Undo
          </button>
          <button type="button" className="btn" disabled={!canRedo(history)} onClick={doRedo}>
            Redo
          </button>
          <button type="button" className="btn" onClick={doInvert}>
            Invert <kbd>I</kbd>
          </button>
          <button type="button" className="btn" onClick={doClear}>
            Clear
          </button>
          <label className="check">
            <input
              type="checkbox"
              checked={showMask}
              onChange={(e) => setShowMask(e.target.checked)}
            />
            Show mask <kbd>H</kbd>
          </label>
          <span className="zoom-level" aria-label="Zoom">
            {pct} %
          </span>
        </div>
      </div>
      <div
        ref={stage}
        className={`mask-stage ${panning ? "panning" : ""}`}
        data-testid="mask-stage"
        role="application"
        aria-label="Mask canvas: drag to paint where the image should change"
        tabIndex={0}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onPointerLeave={() => cursor.current && (cursor.current.style.width = "0px")}
        onContextMenu={(e) => e.preventDefault()}
      >
        <div
          className="mask-layer"
          style={{
            width,
            height,
            transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`,
          }}
        >
          <img src={src} alt="Image to edit" width={width} height={height} draggable={false} />
          <canvas
            ref={mask}
            width={width}
            height={height}
            className="mask-canvas"
            data-testid="mask-canvas"
            style={{
              opacity: showMask ? 0.55 : 0,
              filter: feather > 0 ? `blur(${feather}px)` : undefined,
            }}
          />
        </div>
        <div ref={cursor} className={`brush-cursor ${tool}`} aria-hidden="true" />
      </div>
    </div>
  );
}
