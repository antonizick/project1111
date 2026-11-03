import { beforeEach, expect, it } from "vitest";
import type { Slot } from "../../api/types";
import {
  bindingsOf,
  fillDefaults,
  fuzzyScore,
  missingSlots,
  noteRecent,
  recalled,
  remember,
  runsWithoutInput,
  searchTemplates,
  withRecent,
} from "./slots";
import { template } from "../../test/fakes";

const text = (over: Partial<Slot> = {}): Slot => ({
  name: "scene",
  kind: "text",
  label: "Scene",
  required: true,
  default: null,
  ...over,
});
const face: Slot = { name: "face", kind: "face_image", label: null, required: true, default: null };

beforeEach(() => localStorage.clear());

it("a template runs in one click only when no required slot is open", () => {
  expect(runsWithoutInput({ slots: [] }, {})).toBe(true);
  expect(runsWithoutInput({ slots: [text({ default: "a lake" })] }, {})).toBe(true);
  expect(runsWithoutInput({ slots: [text({ required: false })] }, {})).toBe(true);
  expect(runsWithoutInput({ slots: [text()] }, {})).toBe(false);
  expect(runsWithoutInput({ slots: [text()] }, { scene: "  " })).toBe(false);
  expect(missingSlots({ slots: [text(), face] }, { scene: "x" }).map((s) => s.name)).toEqual([
    "face",
  ]);
  expect(runsWithoutInput({ slots: [face] }, { face: { ref: "img-1" } })).toBe(true);
});

it("builds bindings from the filled slots only", () => {
  const slots = [text(), face, text({ name: "other" })];
  expect(
    bindingsOf(
      { slots },
      { scene: "a lake", face: { ref: "img-1", name: "me.png" }, other: " ", x: "y" },
    ),
  ).toEqual({ scene: "a lake", face: { ref: "img-1" } });
  // an image value cannot fill a text slot and vice versa
  expect(bindingsOf({ slots }, { scene: { ref: "img-1" }, face: "text" })).toEqual({});
});

it("remembers inputs per template and the last five templates run", () => {
  remember("a", { scene: "x" });
  expect(recalled("a")).toEqual({ scene: "x" });
  remember("a", null);
  expect(recalled("a")).toEqual({});
  expect(withRecent(["a", "b", "c"], "b")).toEqual(["b", "a", "c"]);
  let ids: string[] = [];
  for (const id of ["1", "2", "3", "4", "5", "6", "3"]) ids = noteRecent(id);
  expect(ids).toEqual(["3", "6", "5", "4", "2"]);
});

it("fuzzy search ranks prefix and word-start matches first", () => {
  expect(fuzzyScore("xyz", "wallpaper")).toBeNull();
  expect(fuzzyScore("", "anything")).toBe(0);
  const a = template({ id: "a", name: "Software logo dark", folder: "", tags: [] });
  const b = template({ id: "b", name: "Wallpaper photoreal", folder: "", tags: [] });
  const c = template({ id: "c", name: "Indie game logo", folder: "", tags: [] });
  expect(searchTemplates([a, b, c], "wall").map((t) => t.id)).toEqual(["b"]);
  expect(searchTemplates([a, b, c], "slg")[0]?.id).toBe("a");
  expect(
    searchTemplates([a, b, c], "logo")
      .map((t) => t.id)
      .sort(),
  ).toEqual(["a", "c"]);
});

it("fills slot defaults into placeholders for editing", () => {
  expect(fillDefaults("{{ scene }} at dusk, {{missing}}", [text({ default: "a lake" })])).toBe(
    "a lake at dusk, {{missing}}",
  );
});
