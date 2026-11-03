// The pose editor's model (Phase 12): OpenPose-18 people, stock poses, mirroring, hit testing.
// Pure: no DOM, no network. Coordinates are normalised to the picture (0..1), like the API's.

export type Point = [number, number] | null;
export type Person = Point[];
export type PoseData = { people: Person[]; width: number; height: number };

export const KEYPOINTS: readonly string[] = [
  "nose",
  "neck",
  "right shoulder",
  "right elbow",
  "right wrist",
  "left shoulder",
  "left elbow",
  "left wrist",
  "right hip",
  "right knee",
  "right ankle",
  "left hip",
  "left knee",
  "left ankle",
  "right eye",
  "left eye",
  "right ear",
  "left ear",
];

/** OpenPose's limb order and colours (the control image draws exactly this). */
export const LIMBS: readonly [number, number][] = [
  [1, 2], [1, 5], [2, 3], [3, 4], [5, 6], [6, 7], [1, 8], [8, 9], [9, 10],
  [1, 11], [11, 12], [12, 13], [1, 0], [0, 14], [14, 16], [0, 15], [15, 17],
]; // prettier-ignore

export const COLOURS: readonly string[] = [
  "#ff0000", "#ff5500", "#ffaa00", "#ffff00", "#aaff00", "#55ff00", "#00ff00", "#00ff55",
  "#00ffaa", "#00ffff", "#00aaff", "#0055ff", "#0000ff", "#5500ff", "#aa00ff", "#ff00ff",
  "#ff00aa", "#ff0055",
]; // prettier-ignore

/** Left/right pairs swapped when mirroring. */
export const MIRROR_PAIRS: readonly [number, number][] = [
  [2, 5], [3, 6], [4, 7], [8, 11], [9, 12], [10, 13], [14, 15], [16, 17],
]; // prettier-ignore

export const JOINT_RADIUS = 0.012;

function p(x: number, y: number): Point {
  return [x, y];
}

function limbs(points: (readonly [number, readonly [number, number]])[]): Person {
  const out: Person = new Array(KEYPOINTS.length).fill(null);
  for (const [i, xy] of points) out[i] = p(xy[0], xy[1]);
  return out;
}

/**
 * Stock poses, all front view (OpenPose-18 order). Coordinates are proportions of the picture,
 * so a stock pose scales to any aspect: the editor stretches x to keep a person centred.
 */
export const STOCK_POSES: Record<string, Person> = {
  standing: limbs([
    [0, [0.5, 0.16]], [1, [0.5, 0.26]],
    [2, [0.4, 0.27]], [3, [0.37, 0.42]], [4, [0.36, 0.56]],
    [5, [0.6, 0.27]], [6, [0.63, 0.42]], [7, [0.64, 0.56]],
    [8, [0.44, 0.55]], [9, [0.44, 0.73]], [10, [0.44, 0.9]],
    [11, [0.56, 0.55]], [12, [0.56, 0.73]], [13, [0.56, 0.9]],
    [14, [0.48, 0.14]], [15, [0.52, 0.14]], [16, [0.46, 0.15]], [17, [0.54, 0.15]],
  ]), // prettier-ignore
  sitting: limbs([
    [0, [0.5, 0.18]], [1, [0.5, 0.28]],
    [2, [0.4, 0.29]], [3, [0.36, 0.44]], [4, [0.42, 0.52]],
    [5, [0.6, 0.29]], [6, [0.64, 0.44]], [7, [0.58, 0.52]],
    [8, [0.44, 0.56]], [9, [0.6, 0.62]], [10, [0.58, 0.82]],
    [11, [0.56, 0.56]], [12, [0.72, 0.62]], [13, [0.7, 0.82]],
    [14, [0.48, 0.16]], [15, [0.52, 0.16]], [16, [0.46, 0.17]], [17, [0.54, 0.17]],
  ]), // prettier-ignore
  waving: limbs([
    [0, [0.5, 0.17]], [1, [0.5, 0.27]],
    [2, [0.4, 0.28]], [3, [0.35, 0.42]], [4, [0.33, 0.57]],
    [5, [0.6, 0.28]], [6, [0.68, 0.19]], [7, [0.62, 0.07]],
    [8, [0.44, 0.55]], [9, [0.43, 0.73]], [10, [0.42, 0.9]],
    [11, [0.56, 0.55]], [12, [0.57, 0.73]], [13, [0.58, 0.9]],
    [14, [0.48, 0.15]], [15, [0.52, 0.15]], [16, [0.46, 0.16]], [17, [0.54, 0.16]],
  ]), // prettier-ignore
  "arms crossed": limbs([
    [0, [0.5, 0.17]], [1, [0.5, 0.27]],
    [2, [0.4, 0.28]], [3, [0.52, 0.38]], [4, [0.58, 0.47]],
    [5, [0.6, 0.28]], [6, [0.48, 0.38]], [7, [0.42, 0.47]],
    [8, [0.44, 0.55]], [9, [0.43, 0.73]], [10, [0.43, 0.9]],
    [11, [0.56, 0.55]], [12, [0.57, 0.73]], [13, [0.57, 0.9]],
    [14, [0.48, 0.15]], [15, [0.52, 0.15]], [16, [0.46, 0.16]], [17, [0.54, 0.16]],
  ]), // prettier-ignore
  headshot: limbs([
    [0, [0.5, 0.3]], [1, [0.5, 0.52]],
    [2, [0.3, 0.56]], [3, [0.22, 0.78]], [4, [0.2, 0.96]],
    [5, [0.7, 0.56]], [6, [0.78, 0.78]], [7, [0.8, 0.96]],
    [8, [0.36, 0.95]], [9, [0.36, 1.15]], [10, [0.36, 1.3]],
    [11, [0.64, 0.95]], [12, [0.64, 1.15]], [13, [0.64, 1.3]],
    [14, [0.45, 0.26]], [15, [0.55, 0.26]], [16, [0.4, 0.3]], [17, [0.6, 0.3]],
  ]), // prettier-ignore
};

export const STOCK_NAMES: readonly string[] = Object.keys(STOCK_POSES);

export function clonePerson(person: Person): Person {
  return person.map((pt) => (pt ? [pt[0], pt[1]] : null));
}

export function clonePose(data: PoseData): PoseData {
  return { people: data.people.map(clonePerson), width: data.width, height: data.height };
}

export function stockPose(name: string): Person {
  return clonePerson(STOCK_POSES[name] ?? STOCK_POSES.standing ?? []);
}

export function mirrorPerson(person: Person): Person {
  const out = clonePerson(person);
  for (const [a, b] of MIRROR_PAIRS) {
    const left: Point = out[a] ?? null;
    out[a] = out[b] ?? null;
    out[b] = left;
  }
  return out.map((pt) => (pt ? [1 - pt[0], pt[1]] : null));
}

/** Joint under (x, y) (normalised), or -1. The closest joint within ``tol`` wins. */
export function hitTest(person: Person, x: number, y: number, tol = JOINT_RADIUS * 2): number {
  let best = -1;
  let bestD = tol;
  person.forEach((pt, i) => {
    if (!pt) return;
    const d = Math.hypot(pt[0] - x, pt[1] - y);
    if (d <= bestD) {
      bestD = d;
      best = i;
    }
  });
  return best;
}

/** The person with joint ``index`` moved to (x, y), clamped to the picture. */
export function moveJoint(person: Person, index: number, x: number, y: number): Person {
  if (index < 0 || index >= person.length) return person;
  const out = clonePerson(person);
  out[index] = [Math.min(1.2, Math.max(-0.2, x)), Math.min(1.2, Math.max(-0.2, y))];
  return out;
}

/** One person, centred, scaled to the picture's aspect: how a stock pose lands on the canvas. */
export function fitPerson(person: Person, aspect: number): Person {
  // Stock poses are drawn for a portrait 1:1.5 box; widen x when the picture is wider.
  const sx = Math.min(1.6, Math.max(0.7, aspect / (2 / 3)));
  return person.map((pt) => (pt ? [0.5 + (pt[0] - 0.5) * sx, pt[1]] : null));
}

export function personCount(data: PoseData): number {
  return data.people.filter((p) => p.some(Boolean)).length;
}

export function toApiPeople(data: PoseData): (number[] | null)[][] {
  return data.people.map((person) => person.map((pt) => (pt ? [pt[0], pt[1]] : null)));
}
