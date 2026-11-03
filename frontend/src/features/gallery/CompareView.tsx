// Side-by-side compare of two or more images with one shared zoom and pan.

import { useState } from "react";
import type { ImageEntry } from "../../api/types";
import { Dialog } from "../../components/Dialog";
import { RESET, ZoomPan, zoomAt, type ZoomView } from "../../components/ZoomPan";

export function CompareView({ images, onClose }: { images: ImageEntry[]; onClose: () => void }) {
  const [view, setView] = useState<ZoomView>(RESET);
  return (
    <Dialog title={`Compare ${images.length} images`} onClose={onClose} wide>
      <div className="row" role="group" aria-label="Zoom">
        <button type="button" className="btn btn-small" onClick={() => setView(zoomAt(view, 1.25))}>
          Zoom in
        </button>
        <button type="button" className="btn btn-small" onClick={() => setView(zoomAt(view, 0.8))}>
          Zoom out
        </button>
        <button type="button" className="btn btn-small" onClick={() => setView(RESET)}>
          Reset
        </button>
        <span className="muted" aria-live="polite">
          {Math.round(view.scale * 100)} %
        </span>
      </div>
      <div className="compare" data-count={Math.min(images.length, 4)}>
        {images.map((img) => (
          <figure key={img.id} className="compare-pane">
            <ZoomPan src={img.url} alt={img.prompt} view={view} onView={setView} />
            <figcaption>
              #{img.id} · seed {img.seed} · {img.model ?? "?"}
            </figcaption>
          </figure>
        ))}
      </div>
    </Dialog>
  );
}
