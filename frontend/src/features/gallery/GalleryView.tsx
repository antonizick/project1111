// Gallery: virtualized grid by day, search (FTS), filters, selection for compare / bulk export /
// delete (to P11's trash), a detail view and the trash total with "Empty trash".

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { client, saveDownload } from "../../api/client";
import type { Facets, ImageEntry, TrashInfo } from "../../api/types";
import { useNav } from "../../app/nav";
import { useStudio } from "../../app/studio";
import { useToasts } from "../../app/Toasts";
import { Dialog } from "../../components/Dialog";
import { useImageActions } from "../actions";
import { CompareView } from "./CompareView";
import { DetailView } from "./DetailView";
import {
  anchorAt,
  columnsFor,
  layoutRows,
  rowTopOf,
  tileFor,
  totalHeight,
  visibleRows,
  GAP,
  TILE_SIZES,
  type TileSize,
} from "./layout";
import { loadTileSize, saveTileSize } from "./tileSize";

const PAGE = 120;
/** Left + right padding of .gallery-scroll (theme.css). */
const PADDING = 32;

function formatBytes(n: number): string {
  if (n < 1024 * 1024) return `${Math.ceil(n / 1024)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function GalleryView({ active }: { active: boolean }) {
  const { state, dispatch } = useStudio();
  const toasts = useToasts();
  const nav = useNav();
  const actions = useImageActions(() => nav.go("generate"));
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [template, setTemplate] = useState("");
  const [model, setModel] = useState("");
  const [favourites, setFavourites] = useState(false);
  const [items, setItems] = useState<ImageEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [facets, setFacets] = useState<Facets>({ templates: [], models: [] });
  const [selected, setSelected] = useState<number[]>([]);
  const [detail, setDetail] = useState<number | null>(null);
  const [compare, setCompare] = useState(false);
  const [trash, setTrash] = useState<TrashInfo>({ count: 0, bytes: 0 });
  const [confirmEmpty, setConfirmEmpty] = useState(false);
  const [strip, setStrip] = useState(true);
  const [scrollTop, setScrollTop] = useState(0);
  const [size, setSize] = useState({ width: 1000, height: 800 });
  const [tileSize, setTileSize] = useState<TileSize>(loadTileSize);
  const scroller = useRef<HTMLDivElement>(null);
  const anchor = useRef<number | null>(null);
  const loading = useRef(false);

  useEffect(() => {
    const t = setTimeout(() => setQuery(q), 250);
    return () => clearTimeout(t);
  }, [q]);

  const filters = { q: query, template: template || null, model: model || null, favourites };

  const load = useCallback(
    async (offset: number, limit: number) => {
      loading.current = true;
      try {
        const page = await client.gallery({ ...filters, offset, limit });
        dispatch({ type: "cache", images: page.items });
        setItems((prev) => (offset === 0 ? page.items : [...prev, ...page.items]));
        setTotal(page.total);
        setLoaded(true);
      } catch (e) {
        actions.fail(e);
      } finally {
        loading.current = false;
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [query, template, model, favourites],
  );

  // First page on open, filter change, and whenever the gallery changed.
  useEffect(() => {
    if (!active) return;
    // Fetching on change is what this effect is for; `load` sets state only after the await.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load(0, Math.min(500, Math.max(PAGE, items.length)));
    client
      .facets()
      .then(setFacets)
      .catch(() => undefined);
    client
      .trash()
      .then(setTrash)
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, load, state.galleryRev]);

  // ResizeObserver reports the first size on observe; without it (tests) the defaults stand.
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() =>
      setSize({ width: (el.clientWidth || 1032) - PADDING, height: el.clientHeight || 800 }),
    );
    ro.observe(el);
    return () => ro.disconnect();
  }, [active]);

  // Show the latest state of each image (favourites change through events).
  const current = items.map((i) => state.images[i.id] ?? i);
  const tile = tileFor(tileSize);
  const rows = layoutRows(current, columnsFor(size.width, tile), undefined, tile);
  const height = totalHeight(rows);
  const visible = visibleRows(rows, scrollTop, size.height);

  const chooseTileSize = (next: TileSize) => {
    if (next === tileSize) return;
    anchor.current = anchorAt(rows, scrollTop);
    setTileSize(next);
    saveTileSize(next);
  };

  // After a size change, keep the image that was at the top of the view at the top. Reading the
  // scroller and setting state here is the point: the new rows only exist after the render.
  useLayoutEffect(() => {
    const id = anchor.current;
    anchor.current = null;
    if (id === null || scrollTop === 0) return;
    const top = rowTopOf(rows, id);
    if (top === null) return;
    if (scroller.current) scroller.current.scrollTop = top;
    setScrollTop(top);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tileSize]);

  useEffect(() => {
    if (!loading.current && items.length < total && scrollTop + size.height > height - 800)
      void load(items.length, PAGE);
  }, [scrollTop, size.height, height, items.length, total, load]);

  const toggle = (id: number) =>
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  const exportSelected = () =>
    client.exportImages(selected, strip).then(saveDownload).catch(actions.fail);

  const remove = async (ids: number[]) => {
    for (const id of ids) {
      try {
        const r = await client.deleteImage(id);
        setTrash(r.trash);
        dispatch({ type: "deleted", id });
      } catch (e) {
        actions.fail(e);
        return;
      }
    }
    setSelected((s) => s.filter((x) => !ids.includes(x)));
    setItems((prev) => prev.filter((i) => !ids.includes(i.id)));
    toasts.push({
      kind: "info",
      message: `Moved ${ids.length === 1 ? "1 image" : `${ids.length} images`} to the P11 trash.`,
    });
  };

  const detailIndex = current.findIndex((i) => i.id === detail);
  const detailImage = detailIndex >= 0 ? current[detailIndex] : undefined;
  const selectedImages = selected
    .map((id) => current.find((i) => i.id === id) ?? state.images[id])
    .filter((i): i is ImageEntry => i !== undefined);

  return (
    <div className="gallery" hidden={!active}>
      <div className="gallery-toolbar" role="search">
        <label className="sr-only" htmlFor="gallery-search">
          Search prompts
        </label>
        <input
          id="gallery-search"
          type="search"
          placeholder="Search prompts"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <label className="sr-only" htmlFor="gallery-template">
          Filter by template
        </label>
        <select
          id="gallery-template"
          value={template}
          onChange={(e) => setTemplate(e.target.value)}
        >
          <option value="">All templates</option>
          {facets.templates.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <label className="sr-only" htmlFor="gallery-model">
          Filter by model
        </label>
        <select id="gallery-model" value={model} onChange={(e) => setModel(e.target.value)}>
          <option value="">All models</option>
          {facets.models.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="btn"
          aria-pressed={favourites}
          onClick={() => setFavourites(!favourites)}
        >
          ★ Favourites
        </button>
        <div className="chips" role="group" aria-label="Thumbnail size">
          {TILE_SIZES.map((s) => (
            <button
              key={s.id}
              type="button"
              className="chip"
              aria-pressed={tileSize === s.id}
              onClick={() => chooseTileSize(s.id)}
            >
              {s.label}
            </button>
          ))}
        </div>
        <span className="grow" />
        <span className="muted" aria-live="polite">
          {total} {total === 1 ? "image" : "images"}
          {selected.length ? ` · ${selected.length} selected` : ""}
        </span>
      </div>

      {selected.length > 0 && (
        <div className="gallery-toolbar selection" role="group" aria-label="Selection">
          <button
            type="button"
            className="btn"
            disabled={selected.length < 2}
            onClick={() => setCompare(true)}
          >
            Compare
          </button>
          <button type="button" className="btn" onClick={exportSelected}>
            Export {selected.length}
          </button>
          <label className="check">
            <input type="checkbox" checked={strip} onChange={(e) => setStrip(e.target.checked)} />
            Strip metadata
          </label>
          <button type="button" className="btn btn-danger" onClick={() => void remove(selected)}>
            Delete {selected.length}
          </button>
          <button type="button" className="btn btn-ghost" onClick={() => setSelected([])}>
            Clear selection
          </button>
        </div>
      )}

      <div
        className="gallery-scroll"
        ref={scroller}
        onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
      >
        {loaded && total === 0 ? (
          <section className="empty" aria-label="Empty gallery">
            <h2>
              {query || template || model || favourites ? "Nothing matches" : "No images yet"}
            </h2>
            <p>
              {query || template || model || favourites
                ? "Try fewer words or clear the filters."
                : "Images you generate land here, grouped by day."}
            </p>
            {!(query || template || model || favourites) && (
              <button type="button" className="btn btn-primary" onClick={() => nav.go("generate")}>
                Go to Generate
              </button>
            )}
          </section>
        ) : (
          <div className="gallery-canvas" style={{ height }} role="group" aria-label="Images">
            {visible.map((row) =>
              row.kind === "header" ? (
                <h2 key={row.key} className="day" style={{ top: row.top }}>
                  {row.label}
                </h2>
              ) : (
                <div
                  key={row.key}
                  className="tile-row"
                  role="list"
                  style={{ top: row.top, height: row.height }}
                >
                  {row.items.map((img, i) => (
                    <div
                      key={img.id}
                      role="listitem"
                      className={`tile ${selected.includes(img.id) ? "selected" : ""}`}
                      style={{ left: i * (tile + GAP), width: tile, height: tile }}
                    >
                      <button
                        type="button"
                        className="tile-open"
                        aria-label={`Open: ${img.prompt || `image ${img.id}`}`}
                        onClick={() => setDetail(img.id)}
                      >
                        <img src={`${img.thumb}?size=256`} alt="" loading="lazy" />
                      </button>
                      <input
                        type="checkbox"
                        className="tile-check"
                        aria-label={`Select image ${img.id}`}
                        checked={selected.includes(img.id)}
                        onChange={() => toggle(img.id)}
                      />
                      {img.favourite && (
                        <span className="tile-star" aria-label="Favourite">
                          ★
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              ),
            )}
          </div>
        )}
      </div>

      <footer className="gallery-footer">
        <span className="muted">
          Trash: {trash.count} {trash.count === 1 ? "image" : "images"}
          {trash.count ? ` (${formatBytes(trash.bytes)})` : ""}
        </span>
        <button
          type="button"
          className="btn btn-small"
          disabled={trash.count === 0}
          onClick={() => setConfirmEmpty(true)}
        >
          Empty trash
        </button>
      </footer>

      {detailImage && (
        <DetailView
          image={detailImage}
          actions={actions}
          onClose={() => setDetail(null)}
          onPrev={
            detailIndex > 0 ? () => setDetail(current[detailIndex - 1]?.id ?? null) : undefined
          }
          onNext={
            detailIndex < current.length - 1
              ? () => setDetail(current[detailIndex + 1]?.id ?? null)
              : undefined
          }
          onOpenRecipe={() =>
            client
              .recipe(detailImage.id)
              .then((record) => {
                setDetail(null);
                nav.openRecipe(record);
              })
              .catch(actions.fail)
          }
          onDelete={() => {
            const id = detailImage.id;
            setDetail(null);
            void remove([id]);
          }}
        />
      )}
      {compare && selectedImages.length >= 2 && (
        <CompareView images={selectedImages} onClose={() => setCompare(false)} />
      )}
      {confirmEmpty && (
        <Dialog title="Empty the trash?" onClose={() => setConfirmEmpty(false)}>
          <p>
            This deletes {trash.count} {trash.count === 1 ? "image" : "images"} in the P11 trash for
            good. It cannot be undone.
          </p>
          <div className="row">
            <span className="grow" />
            <button type="button" className="btn" onClick={() => setConfirmEmpty(false)}>
              Keep them
            </button>
            <button
              type="button"
              className="btn btn-danger"
              onClick={() =>
                client
                  .emptyTrash()
                  .then((t) => {
                    setTrash(t);
                    setConfirmEmpty(false);
                    toasts.push({ kind: "info", message: "The trash is empty." });
                  })
                  .catch(actions.fail)
              }
            >
              Delete for good
            </button>
          </div>
        </Dialog>
      )}
    </div>
  );
}
