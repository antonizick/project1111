// The four Face & Pose tools as recipes: what the form sends must match schema v1.

import { describe, expect, it } from "vitest";
import {
  CONSENT_NOTICE,
  FACE_SLOT,
  POSE_SLOT,
  REFERENCE_SLOT,
  poseRecipe,
  referenceRecipe,
  restoreRecipe,
  swapRecipe,
} from "./recipe";

const at = { id: "r-face", now: new Date("2026-11-03T10:00:00Z") };

describe("swap face", () => {
  const built = swapRecipe(
    {
      targetRef: "gallery/7",
      faceRef: "img-1",
      sourceFaceIndex: 1,
      targetFaceIndex: 0,
      blend: 0.8,
      restore: true,
      restoreVisibility: 0.6,
    },
    at,
  );

  it("swaps onto the target and takes the face photo as a slot", () => {
    expect(built.recipe.source_image).toEqual({ ref: "gallery/7" });
    expect(built.recipe.slots.map((s) => s.name)).toEqual([FACE_SLOT]);
    expect(built.bindings[FACE_SLOT]).toEqual({ ref: "img-1" });
    expect(built.recipe.steps).toHaveLength(1);
  });

  it("carries the face choice and the restore settings", () => {
    const step = built.recipe.steps[0] as Record<string, unknown>;
    expect(step.type).toBe("face_swap");
    expect(step.source_face_index).toBe(1);
    expect(step.target_face_index).toBe(0);
    expect(step.blend).toBeCloseTo(0.8);
    expect(step.restore).toBe(true);
    expect(step.restore_visibility).toBeCloseTo(0.6);
  });

  it("never carries a way to switch the guard off", () => {
    const step = built.recipe.steps[0] as Record<string, unknown>;
    expect(Object.keys(step).filter((k) => /guard|nsfw/i.test(k))).toEqual([]);
    expect(CONSENT_NOTICE.length).toBeGreaterThan(0);
  });
});

describe("restore faces", () => {
  it("is its own step on the picture", () => {
    const built = restoreRecipe({ targetRef: "gallery/2", faceIndex: 1, visibility: 0.5 }, at);
    const step = built.recipe.steps[0] as Record<string, unknown>;
    expect(step.type).toBe("face_restore");
    expect(step.face_index).toBe(1);
    expect(built.recipe.source_image).toEqual({ ref: "gallery/2" });
    expect(built.bindings).toEqual({});
  });

  it("can restore every face", () => {
    const built = restoreRecipe({ targetRef: "x", faceIndex: null, visibility: 1 }, at);
    expect((built.recipe.steps[0] as Record<string, unknown>).face_index).toBeNull();
  });
});

describe("apply pose", () => {
  const built = poseRecipe(
    {
      prompt: "a dancer on a stage",
      style: "photoreal",
      aspect: "16:9-1920x1080",
      poseRef: "img-9",
      preprocess: false,
      control: "openpose",
      strength: 0.9,
      start: 0,
      end: 1,
    },
    at,
  );

  it("generates and then applies the pose as a modifier", () => {
    expect(built.recipe.steps.map((s) => s.type)).toEqual(["generate", "pose"]);
    const pose = built.recipe.steps[1] as Record<string, unknown>;
    expect(pose.pose_slot).toBe(POSE_SLOT);
    expect(pose.preprocess).toBe(false);
    expect(pose.control).toBe("openpose");
    expect(pose.strength).toBeCloseTo(0.9);
    expect(built.bindings[POSE_SLOT]).toEqual({ ref: "img-9" });
    expect(built.recipe.seed).toEqual({ kind: "random" });
  });

  it("asks the server to read a pose out of a photo when told to", () => {
    const built = poseRecipe(
      {
        prompt: "p",
        style: "photoreal",
        aspect: null,
        poseRef: "img-3",
        preprocess: true,
        control: "depth",
        strength: 1,
        start: 0,
        end: 0.8,
      },
      at,
    );
    const pose = built.recipe.steps[1] as Record<string, unknown>;
    expect(pose.preprocess).toBe(true);
    expect(pose.control).toBe("depth");
  });
});

describe("use as reference", () => {
  it("keeps the style through the IP-Adapter", () => {
    const built = referenceRecipe(
      {
        prompt: "a lighthouse",
        style: "photoreal",
        aspect: null,
        referenceRef: "img-4",
        mode: "style",
        weight: 0.6,
        start: 0,
        end: 1,
      },
      at,
    );
    expect(built.recipe.steps.map((s) => s.type)).toEqual(["generate", "reference"]);
    const ref = built.recipe.steps[1] as Record<string, unknown>;
    expect(ref.image_slot).toBe(REFERENCE_SLOT);
    expect(ref.mode).toBe("style");
    expect(ref.weight).toBeCloseTo(0.6);
    expect(built.bindings[REFERENCE_SLOT]).toEqual({ ref: "img-4" });
  });

  it("uses the face adapter for a character", () => {
    const built = referenceRecipe(
      {
        prompt: "p",
        style: "photoreal",
        aspect: null,
        referenceRef: "img-4",
        mode: "character",
        weight: 1,
        start: 0,
        end: 1,
      },
      at,
    );
    expect((built.recipe.steps[1] as Record<string, unknown>).mode).toBe("character");
  });
});
