// The text overlay editor (Phase 14, R23): type the text, pick a bundled font and look, drag it
// where you want it, and Apply draws it with Pillow at full resolution. The preview is the same
// server-side render the job saves (POST /api/text/preview), so there are no surprises.

import { useEffect, useRef, useState } from "react";
import { client, problemOf } from "../../api/client";
import type { FontInfo, ImageEntry, TextOverlayStep } from "../../api/types";
import { Dialog } from "../../components/Dialog";
import { useToasts } from "../../app/Toasts";
import type { useImageActions } from "../actions";
import {
  DEFAULT_OVERLAY,
  POSITIONS,
  WEIGHTS,
  atPoint,
  draggedPoint,
  hasText,
  sanitize,
  withGradient,
} from "./model";

const LOGO_SIZES = [512, 256, 128, 64, 32];

export function TextOverlayDialog({
  image,
  actions,
  onClose,
}: {
  image: ImageEntry;
  actions: ReturnType<typeof useImageActions>;
  onClose: () => void;
}) {
  const toasts = useToasts();
  const [overlay, setOverlay] = useState<TextOverlayStep>(DEFAULT_OVERLAY);
  const [fonts, setFonts] = useState<FontInfo[]>([]);
  const [preview, setPreview] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [transparent, setTransparent] = useState(true);
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);

  useEffect(() => {
    client
      .fonts()
      .then((r) => setFonts(r.fonts))
      .catch(() => undefined);
  }, []);

  const showPreview = hasText(overlay) && !overlay.also_prompt_model;

  useEffect(() => {
    if (!showPreview) return;
    let cancelled = false;
    let url: string | null = null;
    const timer = setTimeout(() => {
      client
        .textPreview({ image: { ref: `gallery/${image.id}` }, overlay: sanitize(overlay) })
        .then((download) => {
          if (cancelled) return;
          url = URL.createObjectURL(download.blob);
          setPreview(url);
          setError(null);
        })
        .catch((e) => !cancelled && setError(problemOf(e).message));
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      if (url) URL.revokeObjectURL(url);
    };
  }, [overlay, image.id, showPreview]);

  const set = (patch: Partial<TextOverlayStep>) => setOverlay({ ...overlay, ...patch });
  const font = fonts.find((f) => f.id === overlay.font);
  const weights = font?.weights ?? [...WEIGHTS];

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    drag.current = { x: e.clientX, y: e.clientY, ox: overlay.x ?? 0.5, oy: overlay.y ?? 0.5 };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const point = draggedPoint(
      { x: drag.current.ox, y: drag.current.oy },
      e.clientX - drag.current.x,
      e.clientY - drag.current.y,
      { width: rect.width, height: rect.height },
    );
    setOverlay((o) => atPoint(o, point.x, point.y));
  };
  const onPointerUp = () => {
    drag.current = null;
  };

  return (
    <Dialog title="Text & logo" onClose={onClose} wide>
      <div className="text-editor">
        <div className="text-editor-preview" aria-label="Text preview">
          <div
            className="text-drag"
            role="application"
            aria-label="Drag the text to move it"
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
          >
            {showPreview && preview ? (
              <img src={preview} alt={`Text preview: ${overlay.text}`} draggable={false} />
            ) : (
              <div className="text-preview-empty">
                {overlay.also_prompt_model
                  ? "P11 keeps the model's own text: no overlay is drawn."
                  : error || "Type the text to see a preview."}
              </div>
            )}
            {overlay.x !== null && overlay.y !== null && (
              <span
                className="text-crosshair"
                style={{ left: `${overlay.x * 100}%`, top: `${overlay.y * 100}%` }}
                aria-hidden="true"
              />
            )}
          </div>
          <p className="field-help">
            Drag the picture to place the text. The preview is exactly what Apply saves.
          </p>
        </div>

        <div className="text-editor-fields">
          <div className="field">
            <label htmlFor="text-overlay-text">Text</label>
            <textarea
              id="text-overlay-text"
              rows={2}
              maxLength={200}
              value={overlay.text}
              onChange={(e) => set({ text: e.target.value })}
            />
          </div>

          <div className="grid-2">
            <div className="field">
              <label htmlFor="text-font">Font</label>
              <select
                id="text-font"
                value={overlay.font}
                onChange={(e) => set({ font: e.target.value })}
              >
                {fonts.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="text-weight">Weight</label>
              <select
                id="text-weight"
                value={overlay.weight}
                onChange={(e) => set({ weight: e.target.value as TextOverlayStep["weight"] })}
              >
                {weights.map((w) => (
                  <option key={w} value={w}>
                    {w}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="text-size">Size (% of height)</label>
              <input
                id="text-size"
                type="number"
                min={1}
                max={100}
                value={overlay.size_pct}
                onChange={(e) => set({ size_pct: Number(e.target.value) })}
              />
            </div>
            <div className="field">
              <label htmlFor="text-spacing">Letter spacing (em)</label>
              <input
                id="text-spacing"
                type="number"
                min={-0.2}
                max={1}
                step={0.01}
                value={overlay.letter_spacing}
                onChange={(e) => set({ letter_spacing: Number(e.target.value) })}
              />
            </div>
            <div className="field">
              <label htmlFor="text-align">Alignment</label>
              <select
                id="text-align"
                value={overlay.align}
                onChange={(e) => set({ align: e.target.value as TextOverlayStep["align"] })}
              >
                <option value="left">Left</option>
                <option value="center">Centre</option>
                <option value="right">Right</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="text-position">Anchor</label>
              <select
                id="text-position"
                value={overlay.position}
                onChange={(e) => set({ position: e.target.value, x: null, y: null })}
              >
                {POSITIONS.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="text-colour">Colour</label>
              <input
                id="text-colour"
                type="color"
                value={overlay.colour.slice(0, 7)}
                onChange={(e) => set({ colour: e.target.value })}
              />
            </div>
            <div className="field">
              <label htmlFor="text-colour2">Gradient</label>
              <div className="row">
                <input
                  id="text-gradient"
                  type="checkbox"
                  checked={overlay.colour2 !== null}
                  onChange={(e) => setOverlay(withGradient(overlay, e.target.checked))}
                />
                <input
                  id="text-colour2"
                  type="color"
                  disabled={overlay.colour2 === null}
                  value={(overlay.colour2 ?? "#ffd166").slice(0, 7)}
                  onChange={(e) => set({ colour2: e.target.value })}
                />
              </div>
            </div>
            <div className="field">
              <label htmlFor="text-outline">Outline (px)</label>
              <input
                id="text-outline"
                type="number"
                min={0}
                max={64}
                value={overlay.stroke_px}
                onChange={(e) => set({ stroke_px: Number(e.target.value) })}
              />
            </div>
            <label className="check">
              <input
                type="checkbox"
                checked={overlay.shadow}
                onChange={(e) => set({ shadow: e.target.checked })}
              />
              Drop shadow
            </label>
          </div>

          <label className="check">
            <input
              type="checkbox"
              checked={overlay.also_prompt_model}
              onChange={(e) => set({ also_prompt_model: e.target.checked })}
            />
            Let the model try the text (keeps the diffusion text; no overlay)
          </label>

          <div className="row">
            <button
              type="button"
              className="btn btn-primary"
              disabled={!hasText(overlay) || overlay.also_prompt_model}
              onClick={() => {
                actions.addText(image, sanitize(overlay));
                toasts.push({ kind: "info", message: "Drawing the text on a new copy." });
                onClose();
              }}
            >
              Apply text
            </button>
            <button
              type="button"
              className="btn"
              onClick={() => {
                actions.logoVariations(image, 6);
                onClose();
              }}
            >
              6 logo variations
            </button>
            <span className="grow" />
            <label className="check">
              <input
                type="checkbox"
                checked={transparent}
                onChange={(e) => setTransparent(e.target.checked)}
              />
              Transparent
            </label>
            <button
              type="button"
              className="btn"
              onClick={() => {
                actions.logoExport(image, transparent, LOGO_SIZES);
                onClose();
              }}
            >
              Logo pack (PNG + ICO)
            </button>
          </div>
          {font && (
            <p className="field-help">
              {font.label} · {font.licence} · bundled offline.
            </p>
          )}
        </div>
      </div>
    </Dialog>
  );
}
