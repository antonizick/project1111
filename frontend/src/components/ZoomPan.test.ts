import { expect, it } from "vitest";
import { MAX_SCALE, RESET, zoomAt } from "./ZoomPan";

it("zooms around a point and clamps", () => {
  const z = zoomAt(RESET, 2, 100, 0);
  expect(z).toEqual({ scale: 2, x: -100, y: 0 }); // the point under the cursor stays put
  expect(zoomAt(z, 0.1)).toEqual(RESET);
  expect(zoomAt(RESET, 100).scale).toBe(MAX_SCALE);
});
