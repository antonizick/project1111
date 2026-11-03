import { expect, it } from "vitest";
import { commandFor, isTyping } from "./shortcuts";

const key = (key: string, over: Record<string, unknown> = {}) => ({
  key,
  ctrlKey: false,
  metaKey: false,
  altKey: false,
  shiftKey: false,
  target: document.body,
  ...over,
});

it("maps the keyboard", () => {
  const textarea = document.createElement("textarea");
  const checkbox = Object.assign(document.createElement("input"), { type: "checkbox" });
  expect(commandFor(key("Enter", { ctrlKey: true, target: textarea }))).toBe("generate");
  expect(commandFor(key("Escape", { target: textarea }))).toBe("escape");
  expect(commandFor(key("v"))).toBe("variation");
  expect(commandFor(key("T"))).toBe("saveTemplate");
  expect(commandFor(key("g"))).toBe("gallery");
  expect(commandFor(key("?", { shiftKey: true }))).toBe("help");
  expect(commandFor(key("v", { target: textarea }))).toBeNull(); // typing
  expect(commandFor(key("v", { target: checkbox }))).toBe("variation");
  expect(commandFor(key("v", { ctrlKey: true }))).toBeNull();
  expect(commandFor(key("Enter"))).toBeNull();
  expect(isTyping(null)).toBe(false);
  expect(isTyping(document.createElement("select"))).toBe(true);
});
