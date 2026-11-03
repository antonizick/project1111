import { expect, it } from "vitest";
import { baselineSeconds, COLD_START_SECONDS, formatSeconds, remainingSeconds } from "./eta";

it("starts from the benchmark and moves to the observed rate", () => {
  expect(baselineSeconds("realvisxl5-lightning", "16:9-1920x1080", 2)).toBeCloseTo(36.6);
  expect(baselineSeconds("unknown", null, 1)).toBe(30);
  expect(remainingSeconds(0, 0, 18)).toBe(18);
  expect(remainingSeconds(0, 0, 18, true)).toBe(18 + COLD_START_SECONDS);
  expect(remainingSeconds(0.01, 30, 18)).toBe(1); // over the estimate: never below 1 s
  expect(remainingSeconds(0.5, 10, 18)).toBeCloseTo(10); // fully observed at 50 %
  expect(remainingSeconds(1, 20, 18)).toBe(0);
  expect(formatSeconds(0.2)).toBe("almost done");
  expect(formatSeconds(12.2)).toBe("about 13 s left");
  expect(formatSeconds(75)).toBe("about 1 min 15 s left");
});
