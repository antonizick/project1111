// The pose editor's model: joints, stock poses, mirroring and the shape the ControlNet reads.

import { describe, expect, it } from "vitest";
import {
  KEYPOINTS,
  MIRROR_PAIRS,
  STOCK_NAMES,
  STOCK_POSES,
  clonePose,
  fitPerson,
  hitTest,
  mirrorPerson,
  moveJoint,
  personCount,
  stockPose,
  toApiPeople,
  type Person,
} from "./model";

describe("stock poses", () => {
  it("are complete OpenPose-18 skeletons", () => {
    expect(KEYPOINTS).toHaveLength(18);
    for (const name of STOCK_NAMES) {
      const person = STOCK_POSES[name]!;
      expect(person).toHaveLength(18);
      // Every stock pose has a head, a spine and both arms and legs.
      expect(person.every((pt) => pt !== null)).toBe(true);
    }
    expect(STOCK_NAMES).toContain("standing");
    expect(STOCK_NAMES).toContain("headshot");
  });

  it("are copied, never shared", () => {
    const a = stockPose("standing");
    a[0] = [0.1, 0.1];
    expect(stockPose("standing")[0]).not.toEqual([0.1, 0.1]);
  });

  it("fit a wide picture without leaving the middle", () => {
    const wide = fitPerson(stockPose("standing"), 16 / 9);
    const nose = wide[0];
    expect(nose).not.toBeNull();
    expect(nose![0]).toBeGreaterThan(0.3);
    expect(nose![0]).toBeLessThan(0.7);
  });
});

describe("mirroring", () => {
  it("swaps the left and right joints and flips x", () => {
    const person = stockPose("standing");
    const mirrored = mirrorPerson(person);
    for (const [a, b] of MIRROR_PAIRS) {
      expect(mirrored[b]).not.toBeNull();
      expect(mirrored[b]![0]).toBeCloseTo(1 - person[a]![0], 6);
    }
  });

  it("is its own inverse", () => {
    const person = stockPose("waving");
    const twice = mirrorPerson(mirrorPerson(person));
    twice.forEach((pt, i) => {
      if (pt) {
        expect(pt[0]).toBeCloseTo(person[i]![0], 6);
        expect(pt[1]).toBeCloseTo(person[i]![1], 6);
      }
    });
  });

  it("keeps the middle joints in the middle", () => {
    const person = stockPose("standing");
    const mirrored = mirrorPerson(person);
    expect(mirrored[0]![0]).toBeCloseTo(1 - person[0]![0], 6);
  });
});

describe("editing", () => {
  it("finds the joint under the pointer", () => {
    const person = stockPose("standing");
    const nose = person[0]!;
    expect(hitTest(person, nose[0], nose[1])).toBe(0);
    expect(hitTest(person, 0.99, 0.99)).toBe(-1);
  });

  it("moves a joint and clamps it to the picture", () => {
    const moved = moveJoint(stockPose("standing"), 4, -5, 3);
    expect(moved[4]![0]).toBeGreaterThanOrEqual(-0.2);
    expect(moved[4]![1]).toBeLessThanOrEqual(1.2);
  });
});

describe("serialisation", () => {
  it("sends what the API's render expects (nulls for missing joints)", () => {
    const person: Person = stockPose("standing");
    person[3] = null;
    const api = toApiPeople({ people: [person], width: 512, height: 768 });
    expect(api).toHaveLength(1);
    const first = api[0]!;
    expect(first).toHaveLength(18);
    expect(first[3]).toBeNull();
    expect(first[0]).toHaveLength(2);
  });

  it("counts the people that are really there", () => {
    const data = { people: [stockPose("standing"), []], width: 512, height: 768 };
    expect(personCount(data)).toBe(1);
    expect(clonePose(data).people[0]).toHaveLength(18);
    expect(clonePose(data)).not.toBe(data);
  });
});
