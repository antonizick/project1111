// Background form -> recipe JSON (schema v1 `replace_background` step).

import { describe, expect, it } from "vitest";

import type { Presets } from "../../api/types";
import {
  backgroundRecipe,
  describeRecipe,
  HARMONIZE_DENOISE,
  initialBackground,
  MASK_SLOT,
  BACKGROUND_SLOT,
  nearestAspect,
  type BackgroundForm,
  type Source,
} from "./recipe";

const NOW = new Date("2026-11-03T08:00:00Z");

const subject: Source = {
  kind: "gallery",
  id: 7,
  ref: "gallery/7",
  url: "/api/images/7",
  width: 1024,
  height: 1024,
};

function form(patch: Partial<BackgroundForm> = {}): BackgroundForm {
  return { ...initialBackground(), ...patch };
}

describe("backgroundRecipe", () => {
  it("builds a manual-mask step on the subject with a background slot", () => {
    const r = backgroundRecipe(
      form(),
      subject,
      { kind: "photo", ref: "img-bg", url: "x" },
      {
        id: "r1",
        now: NOW,
        seed: null,
      },
    );
    expect(r.source_image).toEqual({ ref: "gallery/7" });
    const step = (r.steps as Record<string, unknown>[])[0]!;
    expect(step.type).toBe("replace_background");
    expect(step.mask_mode).toBe("manual");
    expect(step.mask_slot).toBe(MASK_SLOT);
    expect(step.background_slot).toBe(BACKGROUND_SLOT);
    expect(step.background_colour).toBeNull();
    expect(r.slots.map((s) => s.name)).toEqual([MASK_SLOT, BACKGROUND_SLOT]);
    expect(r.seed).toEqual({ kind: "random" });
  });

  it("maps the harmonize presets to the tuned denoise values", () => {
    const off = backgroundRecipe(
      form({ harmonize: "off" }),
      subject,
      {
        kind: "photo",
        ref: "img-bg",
        url: "x",
      },
      { id: "r", now: NOW, seed: 42 },
    );
    const light = backgroundRecipe(
      form({ harmonize: "light" }),
      subject,
      {
        kind: "photo",
        ref: "img-bg",
        url: "x",
      },
      { id: "r", now: NOW, seed: 42 },
    );
    const strong = backgroundRecipe(
      form({ harmonize: "strong" }),
      subject,
      {
        kind: "photo",
        ref: "img-bg",
        url: "x",
      },
      { id: "r", now: NOW, seed: 42 },
    );
    const s = (r: typeof off) => r.steps[0] as Record<string, unknown>;
    expect(s(off).relight).toBe(false);
    expect(s(light).relight).toBe(true);
    expect(s(light).relight_denoise).toBe(HARMONIZE_DENOISE.light);
    expect(s(strong).relight_denoise).toBe(HARMONIZE_DENOISE.strong);
    expect(HARMONIZE_DENOISE.light).toBeLessThan(HARMONIZE_DENOISE.strong);
    expect(off.seed).toEqual({ kind: "fixed", value: 42 });
  });

  it("sends a flat colour or transparency instead of a background slot", () => {
    const flat = backgroundRecipe(
      form({ harmonize: "light" }),
      subject,
      {
        kind: "colour",
        colour: "#102030",
        transparent: false,
      },
      { id: "r", now: NOW, seed: null },
    );
    const step = flat.steps[0] as Record<string, unknown>;
    expect(step.background_slot).toBeNull();
    expect(step.background_colour).toBe("#102030");
    expect(step.relight).toBe(false); // no photo: no light to match
    expect(flat.slots.map((s) => s.name)).toEqual([MASK_SLOT]);

    const clear = backgroundRecipe(
      form(),
      subject,
      {
        kind: "colour",
        colour: "#102030",
        transparent: true,
      },
      { id: "r", now: NOW, seed: null },
    );
    expect((clear.steps[0] as Record<string, unknown>).background_colour).toBe("#00000000");
  });

  it("passes the geometry and blend options through", () => {
    const r = backgroundRecipe(
      form({
        fit: "contain",
        backgroundX: 0.25,
        subjectScale: 1.5,
        subjectY: 0.75,
        feather: 20,
        colourMatch: false,
        shadow: true,
      }),
      subject,
      { kind: "photo", ref: "img-bg", url: "x" },
      { id: "r", now: NOW, seed: null },
    );
    const step = r.steps[0] as Record<string, unknown>;
    expect(step.fit).toBe("contain");
    expect(step.background_x).toBe(0.25);
    expect(step.subject_scale).toBe(1.5);
    expect(step.subject_y).toBe(0.75);
    expect(step.feather_px).toBe(20);
    expect(step.colour_match).toBe(false);
    expect(step.shadow).toBe(true);
  });
});

describe("describeRecipe", () => {
  it("is a one-step photoreal generate at the given aspect", () => {
    const r = describeRecipe("a sunny beach", "1:1-1024", { id: "r2", now: NOW });
    expect(r.steps).toHaveLength(1);
    const step = r.steps[0] as Record<string, unknown>;
    expect(step.type).toBe("generate");
    expect(step.prompt).toBe("a sunny beach");
    expect(step.aspect).toBe("1:1-1024");
  });
});

describe("nearestAspect", () => {
  const presets: Presets = {
    aspects: [
      {
        id: "16:9-1920x1080",
        label: "16:9",
        output: [1920, 1080],
        bucket: {},
        chain: "model",
        quality_chain: "latent",
      },
      {
        id: "1:1-1024",
        label: "1:1",
        output: [1024, 1024],
        bucket: {},
        chain: "native",
        quality_chain: "native",
      },
    ],
    styles: [],
  };

  it("picks the closest output ratio", () => {
    expect(nearestAspect(presets, 1000, 1000)).toBe("1:1-1024");
    expect(nearestAspect(presets, 1920, 1080)).toBe("16:9-1920x1080");
  });

  it("returns null without presets or a size", () => {
    expect(nearestAspect(null, 100, 100)).toBeNull();
    expect(nearestAspect(presets, 0, 100)).toBeNull();
  });
});
