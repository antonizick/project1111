// Virtualized gallery layout: images grouped by local day into header rows and tile rows of
// fixed height, so only the rows in view are rendered. Pure.

import type { ImageEntry } from "../../api/types";

export const TILE = 200;
export const SMALL_TILE = 120;
export const GAP = 8;
export const HEADER = 40;
export const ROW = TILE + GAP;

export type TileSize = "small" | "medium";

export const TILE_SIZES: { id: TileSize; label: string; tile: number }[] = [
  { id: "small", label: "Small", tile: SMALL_TILE },
  { id: "medium", label: "Medium", tile: TILE },
];

export function tileFor(size: TileSize): number {
  return size === "small" ? SMALL_TILE : TILE;
}

export type Row =
  | { kind: "header"; key: string; label: string; top: number; height: number }
  | { kind: "tiles"; key: string; items: ImageEntry[]; top: number; height: number };

export function dayKey(iso: string): string {
  const d = new Date(iso);
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

export function dayLabel(key: string, today: Date = new Date()): string {
  const todayKey = dayKey(today.toISOString());
  const y = new Date(today);
  y.setDate(y.getDate() - 1);
  if (key === todayKey) return "Today";
  if (key === dayKey(y.toISOString())) return "Yesterday";
  const [yy, mm, dd] = key.split("-").map(Number);
  return new Date(yy ?? 1970, (mm ?? 1) - 1, dd ?? 1).toLocaleDateString(undefined, {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

export function columnsFor(width: number, tile: number = TILE): number {
  return Math.max(1, Math.floor((width + GAP) / (tile + GAP)));
}

/** Rows for `items` (newest first) in `columns` columns of `tile` px, with their offsets. */
export function layoutRows(
  items: ImageEntry[],
  columns: number,
  today?: Date,
  tile: number = TILE,
): Row[] {
  const row = tile + GAP;
  const rows: Row[] = [];
  let top = 0;
  let current: string | null = null;
  let tiles: ImageEntry[] = [];
  const flush = () => {
    if (!tiles.length) return;
    rows.push({ kind: "tiles", key: `t-${tiles[0]?.id}`, items: tiles, top, height: row });
    top += row;
    tiles = [];
  };
  for (const item of items) {
    const key = dayKey(item.created_at);
    if (key !== current) {
      flush();
      current = key;
      rows.push({
        kind: "header",
        key: `h-${key}`,
        label: dayLabel(key, today),
        top,
        height: HEADER,
      });
      top += HEADER;
    }
    tiles.push(item);
    if (tiles.length === columns) flush();
  }
  flush();
  return rows;
}

export function totalHeight(rows: Row[]): number {
  const last = rows[rows.length - 1];
  return last ? last.top + last.height : 0;
}

/** The first image at or below `scrollTop`: what stays in view when the tile size changes. */
export function anchorAt(rows: Row[], scrollTop: number): number | null {
  for (const r of rows)
    if (r.kind === "tiles" && r.top + r.height > scrollTop) return r.items[0]?.id ?? null;
  return null;
}

/** Top of the tile row holding image `id`, or null. */
export function rowTopOf(rows: Row[], id: number): number | null {
  for (const r of rows) if (r.kind === "tiles" && r.items.some((i) => i.id === id)) return r.top;
  return null;
}

/** Rows that intersect [scrollTop - overscan, scrollTop + height + overscan]. */
export function visibleRows(rows: Row[], scrollTop: number, height: number, overscan = 400): Row[] {
  const lo = scrollTop - overscan;
  const hi = scrollTop + height + overscan;
  return rows.filter((r) => r.top + r.height >= lo && r.top <= hi);
}
