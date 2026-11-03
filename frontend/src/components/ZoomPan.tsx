// An image with wheel/keyboard zoom and drag pan. Pass `view` + `onView` to control it, so
// the compare view can keep several images in sync.

import { useEffect, useRef, useState } from "react";

export type ZoomView = { scale: number; x: number; y: number };
export const RESET: ZoomView = { scale: 1, x: 0, y: 0 };
export const MIN_SCALE = 1;
export const MAX_SCALE = 8;

/** Zoom by `factor` keeping the point (px, py), relative to the centre, where it is. */
export function zoomAt(v: ZoomView, factor: number, px = 0, py = 0): ZoomView {
  const scale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, v.scale * factor));
  if (scale === MIN_SCALE) return RESET;
  const k = scale / v.scale;
  return { scale, x: px - (px - v.x) * k, y: py - (py - v.y) * k };
}

export function ZoomPan({
  src,
  alt,
  view: controlled,
  onView,
  className = "",
}: {
  src: string;
  alt: string;
  view?: ZoomView;
  onView?: (v: ZoomView) => void;
  className?: string;
}) {
  const [own, setOwn] = useState<ZoomView>(RESET);
  const view = controlled ?? own;
  const setView = onView ?? setOwn;
  const box = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null);
  const latest = useRef({ view, setView });
  useEffect(() => {
    latest.current = { view, setView };
  });

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const px = e.clientX - r.left - r.width / 2;
      const py = e.clientY - r.top - r.height / 2;
      const { view: v, setView: set } = latest.current;
      set(zoomAt(v, e.deltaY < 0 ? 1.2 : 1 / 1.2, px, py));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const onKeyDown = (e: React.KeyboardEvent) => {
    const step = 40;
    const moves: Record<string, () => ZoomView> = {
      "+": () => zoomAt(view, 1.25),
      "=": () => zoomAt(view, 1.25),
      "-": () => zoomAt(view, 0.8),
      "0": () => RESET,
      ArrowLeft: () => ({ ...view, x: view.x + step }),
      ArrowRight: () => ({ ...view, x: view.x - step }),
      ArrowUp: () => ({ ...view, y: view.y + step }),
      ArrowDown: () => ({ ...view, y: view.y - step }),
    };
    const move = moves[e.key];
    if (!move || (e.key.startsWith("Arrow") && view.scale === 1)) return;
    e.preventDefault();
    e.stopPropagation();
    setView(move());
  };

  return (
    <div
      ref={box}
      className={`zoompan ${view.scale > 1 ? "zoomed" : ""} ${className}`}
      tabIndex={0}
      role="img"
      aria-label={`${alt} (zoom ${Math.round(view.scale * 100)} %; + and − to zoom, 0 to reset)`}
      onKeyDown={onKeyDown}
      onDoubleClick={() => setView(view.scale > 1 ? RESET : zoomAt(view, 2))}
      onPointerDown={(e) => {
        if (view.scale === 1) return;
        drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y };
        e.currentTarget.setPointerCapture?.(e.pointerId);
      }}
      onPointerMove={(e) => {
        const d = drag.current;
        if (!d) return;
        setView({ ...view, x: d.vx + e.clientX - d.x, y: d.vy + e.clientY - d.y });
      }}
      onPointerUp={() => (drag.current = null)}
      onPointerCancel={() => (drag.current = null)}
    >
      <img
        src={src}
        alt=""
        draggable={false}
        style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})` }}
      />
    </div>
  );
}
