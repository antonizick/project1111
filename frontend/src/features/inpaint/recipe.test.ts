import { expect, it } from "vitest";
import { initialInpaint, inpaintRecipe, type Source } from "./recipe";

const gallery: Source = {
  kind: "gallery",
  id: 7,
  url: "/api/images/7",
  width: 1920,
  height: 1080,
  model: "realvisxl5-lightning",
};
const opts = { id: "abc", now: new Date("2026-11-03T10:00:00Z") };

it("builds a preset inpaint of a gallery image with a mask slot", () => {
  const r = inpaintRecipe(initialInpaint("a red scarf"), gallery, opts);
  expect(r.source_image).toEqual({ ref: "gallery/7" });
  expect(r.slots).toEqual([
    { name: "mask", kind: "mask", label: "Mask", required: true, default: null },
  ]);
  expect(r.seed).toEqual({ kind: "random" });
  expect(r.steps[0]).toMatchObject({
    type: "inpaint",
    mask_slot: "mask",
    prompt: "a red scarf",
    denoise_preset: "balanced",
    crop: true,
    mask_blur_px: 12,
    padding_px: 48,
    model: { manifest_id: "realvisxl5-lightning" },
    sampler: null,
  });
});

it("uses advanced values over the preset", () => {
  const form = { ...initialInpaint(""), denoise: 0.42, steps: 12, seed: 99, crop: false };
  const upload: Source = { kind: "upload", id: "img-1", url: "blob:x", width: 10, height: 10 };
  const r = inpaintRecipe(form, upload, opts);
  expect(r.source_image).toEqual({ ref: "img-1" });
  expect(r.seed).toEqual({ kind: "fixed", value: 99 });
  expect(r.steps[0]).toMatchObject({
    denoise: 0.42,
    denoise_preset: null,
    crop: false,
    model: null,
    sampler: { steps: 12 },
  });
});
