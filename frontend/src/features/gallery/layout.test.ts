import { expect, it } from "vitest";
import { image } from "../../test/fakes";
import {
  anchorAt,
  columnsFor,
  dayKey,
  dayLabel,
  HEADER,
  layoutRows,
  ROW,
  rowTopOf,
  SMALL_TILE,
  tileFor,
  totalHeight,
  visibleRows,
} from "./layout";

const local = (y: number, m: number, d: number, h = 12) => new Date(y, m - 1, d, h).toISOString();

it("groups by local day into header and tile rows", () => {
  const items = [
    ...[1, 2, 3, 4, 5].map((i) => image(i, { created_at: local(2026, 11, 3) })),
    ...[6, 7].map((i) => image(i, { created_at: local(2026, 11, 2) })),
  ];
  const rows = layoutRows(items, 2, new Date(2026, 10, 3, 18));
  expect(rows.map((r) => (r.kind === "header" ? r.label : r.items.map((i) => i.id)))).toEqual([
    "Today",
    [1, 2],
    [3, 4],
    [5],
    "Yesterday",
    [6, 7],
  ]);
  expect(rows[1]?.top).toBe(HEADER);
  expect(totalHeight(rows)).toBe(2 * HEADER + 4 * ROW);
  expect(visibleRows(rows, 0, 100, 0).map((r) => r.key)).toEqual(["h-2026-11-03", rows[1]?.key]);
  expect(totalHeight([])).toBe(0);
});

it("columns and labels", () => {
  expect(columnsFor(100)).toBe(1);
  expect(columnsFor(ROW * 4)).toBe(4);
  expect(dayKey(local(2026, 1, 5))).toBe("2026-01-05");
  expect(dayLabel("2026-01-05", new Date(2026, 10, 3))).toMatch(/2026/);
});

it("lays out both tile sizes", () => {
  const items = [1, 2, 3, 4, 5].map((i) => image(i, { created_at: local(2026, 11, 3) }));
  expect(columnsFor(1000, tileFor("medium"))).toBe(4);
  expect(columnsFor(1000, tileFor("small"))).toBe(7);
  expect(columnsFor(10, SMALL_TILE)).toBe(1);
  const small = layoutRows(items, 2, undefined, SMALL_TILE);
  expect(small.filter((r) => r.kind === "tiles").map((r) => r.height)).toEqual([128, 128, 128]);
  expect(totalHeight(small)).toBe(HEADER + 3 * 128);
  expect(totalHeight(layoutRows(items, 2))).toBe(HEADER + 3 * ROW);
});

it("finds the image to keep in view across a size change", () => {
  const items = [1, 2, 3, 4, 5].map((i) => image(i, { created_at: local(2026, 11, 3) }));
  const rows = layoutRows(items, 2);
  expect(anchorAt(rows, HEADER + ROW + 10)).toBe(3);
  expect(anchorAt(rows, 1e6)).toBeNull();
  expect(rowTopOf(layoutRows(items, 4, undefined, SMALL_TILE), 5)).toBe(HEADER + 128);
  expect(rowTopOf(rows, 99)).toBeNull();
});
