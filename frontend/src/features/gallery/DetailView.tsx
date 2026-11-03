// One gallery image, large: zoom/pan, metadata, actions, open as recipe, previous/next.

import type { ImageEntry } from "../../api/types";
import { useShortcuts } from "../../app/shortcuts";
import { Dialog } from "../../components/Dialog";
import { ZoomPan } from "../../components/ZoomPan";
import type { useImageActions } from "../actions";
import { ImageActions, ImageMeta } from "../generate/ResultPanel";

export function DetailView({
  image,
  actions,
  onClose,
  onPrev,
  onNext,
  onOpenRecipe,
  onDelete,
}: {
  image: ImageEntry;
  actions: ReturnType<typeof useImageActions>;
  onClose: () => void;
  onPrev?: () => void;
  onNext?: () => void;
  onOpenRecipe: () => void;
  onDelete: () => void;
}) {
  useShortcuts({
    variation: () => actions.variations(image, "seed"),
    saveTemplate: () => actions.later("template"),
  });
  return (
    <Dialog title={image.prompt || `Image ${image.id}`} onClose={onClose} wide>
      <div
        className="detail"
        onKeyDown={(e) => {
          if (e.target instanceof HTMLElement && e.target.closest(".zoompan")) return;
          if (e.key === "ArrowLeft" && onPrev) onPrev();
          if (e.key === "ArrowRight" && onNext) onNext();
        }}
      >
        <ZoomPan key={image.id} src={image.url} alt={image.prompt} className="detail-image" />
        <aside className="detail-side">
          <div className="row">
            <button type="button" className="btn" disabled={!onPrev} onClick={onPrev}>
              ← Previous
            </button>
            <button type="button" className="btn" disabled={!onNext} onClick={onNext}>
              Next →
            </button>
          </div>
          <button type="button" className="btn" onClick={onOpenRecipe}>
            Open as recipe
          </button>
          <ImageActions image={image} actions={actions} />
          <ImageMeta image={image} />
          <button type="button" className="btn btn-danger" onClick={onDelete}>
            Delete (move to trash)
          </button>
        </aside>
      </div>
    </Dialog>
  );
}
