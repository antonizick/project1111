// The Upscale follow-up (Phase 14): Speed (model only) or Quality (model + refinement), at a
// factor or to a wallpaper size. The recipe is built by `upscaleRecipe`.

import { useState } from "react";
import type { ImageEntry } from "../../api/types";
import { Dialog } from "../../components/Dialog";
import type { UpscaleOptions } from "./form";

const CHOICES: { id: string; label: string; options: UpscaleOptions }[] = [
  { id: "1.5", label: "×1.5", options: { scale: 1.5 } },
  { id: "2", label: "×2", options: { scale: 2 } },
  { id: "1080", label: "To 1920 × 1080", options: { width: 1920, height: 1080 } },
  { id: "1440", label: "To 2560 × 1440", options: { width: 2560, height: 1440 } },
];

export function UpscaleDialog({
  image,
  onClose,
  onRun,
}: {
  image: ImageEntry;
  onClose: () => void;
  onRun: (options: UpscaleOptions) => void;
}) {
  const [choice, setChoice] = useState("2");
  const [quality, setQuality] = useState(false);
  const selected = CHOICES.find((c) => c.id === choice) ?? CHOICES[1]!;
  return (
    <Dialog title="Upscale" onClose={onClose}>
      <fieldset className="field">
        <legend>Size</legend>
        <div className="chips">
          {CHOICES.map((c) => (
            <button
              key={c.id}
              type="button"
              className="chip"
              aria-pressed={choice === c.id}
              onClick={() => setChoice(c.id)}
            >
              {c.label}
            </button>
          ))}
        </div>
      </fieldset>
      <fieldset className="field">
        <legend>Mode</legend>
        <div className="chips">
          <button
            type="button"
            className="chip"
            aria-pressed={!quality}
            onClick={() => setQuality(false)}
          >
            Speed
          </button>
          <button
            type="button"
            className="chip"
            aria-pressed={quality}
            onClick={() => setQuality(true)}
          >
            Quality
          </button>
        </div>
        <p className="field-help">
          {quality
            ? "Adds a refinement pass: sharper detail, about 45–66 s at wallpaper size."
            : "Model upscaler only: crisp and fast, about 18 s at wallpaper size."}
        </p>
      </fieldset>
      <div className="row">
        <span className="grow" />
        <button type="button" className="btn" onClick={onClose}>
          Cancel
        </button>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => {
            onRun({ ...selected.options, quality });
            onClose();
          }}
        >
          Upscale {selected.label}
        </button>
      </div>
      <p className="field-help">
        From {image.width ?? "?"} × {image.height ?? "?"}. The result is saved in the gallery.
      </p>
    </Dialog>
  );
}
