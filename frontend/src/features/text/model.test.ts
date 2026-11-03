import { expect, it } from "vitest";
import {
  DEFAULT_OVERLAY,
  atPoint,
  clamp01,
  draggedPoint,
  hasText,
  sanitize,
  withGradient,
} from "./model";

it("clamps points and turns a drag into fractions", () => {
  expect(clamp01(-1)).toBe(0);
  expect(clamp01(2)).toBe(1);
  expect(clamp01(Number.NaN)).toBe(0);
  expect(draggedPoint({ x: 0.5, y: 0.5 }, 100, -50, { width: 400, height: 200 })).toEqual({
    x: 0.75,
    y: 0.25,
  });
  expect(draggedPoint({ x: 0.9, y: 0.1 }, 500, -500, { width: 400, height: 200 })).toEqual({
    x: 1,
    y: 0,
  });
});

it("a dragged point switches the anchor off", () => {
  const moved = atPoint(DEFAULT_OVERLAY, 0.25, 0.75);
  expect(moved.x).toBe(0.25);
  expect(moved.y).toBe(0.75);
});

it("the gradient control keeps a second colour only while it is on", () => {
  const on = withGradient(DEFAULT_OVERLAY, true);
  expect(on.colour2).toMatch(/^#/);
  const off = withGradient(on, false);
  expect(off.colour2).toBeNull();
});

it("sanitises numbers and trims the text before it goes to the API", () => {
  const fixed = sanitize({
    ...DEFAULT_OVERLAY,
    text: "  Product  ",
    size_pct: 0,
    margin_pct: 99,
    letter_spacing: 9,
    stroke_px: -3,
    x: 4,
    y: -2,
  });
  expect(fixed.text).toBe("Product");
  expect(fixed.size_pct).toBe(0.5);
  expect(fixed.margin_pct).toBe(50);
  expect(fixed.letter_spacing).toBe(1);
  expect(fixed.stroke_px).toBe(0);
  expect(fixed.x).toBe(1);
  expect(fixed.y).toBe(0);
  expect(hasText(DEFAULT_OVERLAY)).toBe(true);
  expect(hasText({ ...DEFAULT_OVERLAY, text: "   " })).toBe(false);
});
