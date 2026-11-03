// The latest result: zoomable image, a metadata summary and its follow-up actions (R18).

import { useState } from "react";
import type { ImageEntry } from "../../api/types";
import { ZoomPan } from "../../components/ZoomPan";
import { LATER, useImageActions } from "../actions";

export function ImageMeta({ image }: { image: ImageEntry }) {
  return (
    <dl className="meta">
      <dt>Prompt</dt>
      <dd>{image.prompt || "—"}</dd>
      <dt>Size</dt>
      <dd>{image.width && image.height ? `${image.width} × ${image.height}` : "—"}</dd>
      <dt>Seed</dt>
      <dd>{image.seed}</dd>
      <dt>Model</dt>
      <dd>{image.model ?? "—"}</dd>
      <dt>Made</dt>
      <dd>{new Date(image.created_at).toLocaleString()}</dd>
    </dl>
  );
}

export function ImageActions({
  image,
  actions,
  batch = 1,
}: {
  image: ImageEntry;
  actions: ReturnType<typeof useImageActions>;
  batch?: number;
}) {
  const [strip, setStrip] = useState(true);
  return (
    <div className="actions" role="group" aria-label="Image actions">
      <button
        type="button"
        className="btn"
        onClick={() => actions.variations(image, "seed", batch)}
      >
        Variations <kbd>V</kbd>
      </button>
      <button type="button" className="btn" onClick={() => actions.variations(image, "prompt")}>
        Tweak prompt
      </button>
      <button type="button" className="btn" onClick={() => actions.upscale(image)}>
        Upscale ×2
      </button>
      <button type="button" className="btn" onClick={() => actions.inpaint(image)}>
        Inpaint
      </button>
      {(["background", "face"] as const).map((k) => (
        <button
          key={k}
          type="button"
          className="btn btn-later"
          aria-disabled="true"
          title={`Coming in Phase ${LATER[k]?.phase}`}
          onClick={() => actions.later(k)}
        >
          {LATER[k]?.label} <small>Phase {LATER[k]?.phase}</small>
        </button>
      ))}
      <button type="button" className="btn" onClick={() => actions.saveTemplate(image)}>
        Save as Template <kbd>T</kbd>
      </button>
      <button
        type="button"
        className="btn"
        aria-pressed={image.favourite}
        onClick={() => actions.favourite(image)}
      >
        {image.favourite ? "★ Favourite" : "☆ Favourite"}
      </button>
      <span className="download">
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => actions.download(image, strip)}
        >
          Download
        </button>
        <label className="check">
          <input type="checkbox" checked={strip} onChange={(e) => setStrip(e.target.checked)} />
          Strip metadata
        </label>
      </span>
    </div>
  );
}

export function ResultPanel({
  images,
  index,
  setIndex,
  actions,
  batch,
}: {
  images: ImageEntry[];
  index: number;
  setIndex: (i: number) => void;
  actions: ReturnType<typeof useImageActions>;
  batch: number;
}) {
  const image = images[Math.min(index, images.length - 1)];
  if (!image) return null;
  return (
    <section className="result" aria-label="Result">
      <ZoomPan src={image.url} alt={`Result: ${image.prompt}`} className="result-image" />
      {images.length > 1 && (
        <div className="strip" role="group" aria-label="Batch results">
          {images.map((img, i) => (
            <button
              key={img.id}
              type="button"
              className="strip-item"
              aria-pressed={img.id === image.id}
              aria-label={`Result ${i + 1} of ${images.length}`}
              onClick={() => setIndex(i)}
            >
              <img src={img.thumb} alt="" />
            </button>
          ))}
        </div>
      )}
      <ImageActions image={image} actions={actions} batch={batch} />
      <ImageMeta image={image} />
    </section>
  );
}
