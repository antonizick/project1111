import { expect, it } from "vitest";
import { image } from "../../test/fakes";
import {
  columnsFor,
  dayKey,
  dayLabel,
  HEADER,
  layoutRows,
  ROW,
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
