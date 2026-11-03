// Virtualized gallery layout: images grouped by local day into header rows and tile rows of
// fixed height, so only the rows in view are rendered. Pure.

import type { ImageEntry } from "../../api/types";

export const TILE = 200;
export const GAP = 8;
export const HEADER = 40;
export const ROW = TILE + GAP;

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

export function columnsFor(width: number): number {
  return Math.max(1, Math.floor((width + GAP) / ROW));
}

/** Rows for `items` (newest first) in `columns` columns, with their offsets. */
export function layoutRows(items: ImageEntry[], columns: number, today?: Date): Row[] {
  const rows: Row[] = [];
  let top = 0;
  let current: string | null = null;
  let tiles: ImageEntry[] = [];
  const flush = () => {
    if (!tiles.length) return;
    rows.push({ kind: "tiles", key: `t-${tiles[0]?.id}`, items: tiles, top, height: ROW });
    top += ROW;
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

/** Rows that intersect [scrollTop - overscan, scrollTop + height + overscan]. */
export function visibleRows(rows: Row[], scrollTop: number, height: number, overscan = 400): Row[] {
  const lo = scrollTop - overscan;
  const hi = scrollTop + height + overscan;
  return rows.filter((r) => r.top + r.height >= lo && r.top <= hi);
}
