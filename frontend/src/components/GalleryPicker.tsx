// "From gallery": a button and a dialog to choose an image P11 already holds. It hands back the
// gallery entry, never bytes: the caller passes a `gallery/<id>` reference, which is how the S5
// likeness flag travels (ADR-0046). The dialog renders in document.body, because most image inputs
// sit inside a form and Enter in its search box must not submit that form.

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { client, problemOf } from "../api/client";
import type { ImageEntry } from "../api/types";
import { useToasts } from "../app/Toasts";
import { Dialog } from "./Dialog";

const PAGE = 60;

export function GalleryPicker({
  label,
  onPick,
  disabled = false,
  className = "btn btn-small from-gallery",
}: {
  /** What the picture is for, e.g. "Face photo": names the button and the dialog. */
  label: string;
  onPick: (image: ImageEntry) => void;
  disabled?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className={className} disabled={disabled} onClick={() => setOpen(true)}>
        From gallery <span className="sr-only">for {label}</span>
      </button>
      {open &&
        createPortal(
          <PickerDialog
            label={label}
            onClose={() => setOpen(false)}
            onPick={(image) => {
              setOpen(false);
              onPick(image);
            }}
          />,
          document.body,
        )}
    </>
  );
}

function PickerDialog({
  label,
  onClose,
  onPick,
}: {
  label: string;
  onClose: () => void;
  onPick: (image: ImageEntry) => void;
}) {
  const toasts = useToasts();
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<ImageEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [more, setMore] = useState(false);
  const seq = useRef(0);

  useEffect(() => {
    const t = setTimeout(() => setQuery(q), 250);
    return () => clearTimeout(t);
  }, [q]);

  const load = async (offset: number) => {
    const mine = ++seq.current;
    try {
      const page = await client.gallery({ q: query, offset, limit: PAGE });
      if (seq.current !== mine) return; // a newer search answered first
      setItems((prev) => (offset === 0 ? page.items : [...prev, ...page.items]));
      setTotal(page.total);
      setLoaded(true);
    } catch (e) {
      if (seq.current === mine) toasts.problem(problemOf(e));
    } finally {
      if (seq.current === mine) setMore(false);
    }
  };

  useEffect(() => {
    // Fetching on change is what this effect is for; `load` sets state only after the await.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query]);

  return (
    <Dialog title={`${label}: choose from the gallery`} onClose={onClose}>
      <label className="sr-only" htmlFor="picker-search">
        Search prompts
      </label>
      <input
        id="picker-search"
        type="search"
        data-autofocus
        placeholder="Search prompts"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      {loaded && items.length === 0 ? (
        <p className="field-help" role="status">
          {query ? "Nothing matches. Try fewer words." : "No images yet. Generate one first."}
        </p>
      ) : (
        <div className="picker-grid" role="group" aria-label="Gallery images">
          {items.map((img) => (
            <button
              key={img.id}
              type="button"
              className="picker-tile"
              title={img.prompt || `Image ${img.id}`}
              onClick={() => onPick(img)}
            >
              <img
                src={`${img.thumb}?size=256`}
                alt={img.prompt || `Image ${img.id}`}
                loading="lazy"
              />
            </button>
          ))}
        </div>
      )}
      {items.length < total && (
        <button
          type="button"
          className="btn"
          disabled={more}
          onClick={() => {
            setMore(true);
            void load(items.length);
          }}
        >
          Show more ({total - items.length} left)
        </button>
      )}
    </Dialog>
  );
}
