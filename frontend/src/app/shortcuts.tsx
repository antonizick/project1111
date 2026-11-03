// The keyboard map (Phase 08 task 8) and the registry views use to handle shortcuts.
// The shell listens on the window; the most recently registered handler for a command wins, so
// a dialog that registers `escape` closes before the view under it cancels a job.

import { createContext, useContext, useEffect, useMemo, useRef, type ReactNode } from "react";

export type Command = "generate" | "escape" | "variation" | "saveTemplate" | "gallery" | "help";

export const SHORTCUTS: { keys: string; command: Command; label: string }[] = [
  { keys: "Ctrl+Enter", command: "generate", label: "Generate" },
  { keys: "Esc", command: "escape", label: "Cancel the running job, or close a dialog" },
  { keys: "V", command: "variation", label: "Variations of the shown image" },
  { keys: "T", command: "saveTemplate", label: "Save as template" },
  { keys: "G", command: "gallery", label: "Go to the gallery" },
  { keys: "?", command: "help", label: "Show these shortcuts" },
];

type KeyLike = Pick<KeyboardEvent, "key" | "ctrlKey" | "metaKey" | "altKey" | "shiftKey"> & {
  target: EventTarget | null;
};

export function isTyping(target: EventTarget | null): boolean {
  if (!target || !(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  if (tag === "TEXTAREA" || tag === "SELECT") return true;
  if (tag !== "INPUT") return false;
  const type = (target as HTMLInputElement).type;
  return !["checkbox", "radio", "button", "submit", "range"].includes(type);
}

/** The command a key press means, or null. Letter keys are ignored while typing in a field. */
export function commandFor(e: KeyLike): Command | null {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) return "generate";
  if (e.key === "Escape") return "escape";
  if (e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target)) return null;
  if (e.key === "?") return "help";
  if (e.shiftKey) return null;
  switch (e.key.toLowerCase()) {
    case "v":
      return "variation";
    case "t":
      return "saveTemplate";
    case "g":
      return "gallery";
  }
  return null;
}

export type Handlers = Partial<Record<Command, () => void>>;

type Registry = { register: (h: { current: Handlers }) => () => void };
const ShortcutContext = createContext<Registry | null>(null);

export function ShortcutProvider({ children }: { children: ReactNode }) {
  const stack = useRef<{ current: Handlers }[]>([]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const command = commandFor(e);
      if (!command) return;
      for (let i = stack.current.length - 1; i >= 0; i--) {
        const handler = stack.current[i]?.current[command];
        if (handler) {
          e.preventDefault();
          handler();
          return;
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const value = useMemo<Registry>(
    () => ({
      register: (h) => {
        stack.current.push(h);
        return () => {
          stack.current = stack.current.filter((x) => x !== h);
        };
      },
    }),
    [],
  );
  return <ShortcutContext.Provider value={value}>{children}</ShortcutContext.Provider>;
}

/** Handle shortcuts while the calling component is mounted (and `active`). */
export function useShortcuts(handlers: Handlers, active = true): void {
  const registry = useContext(ShortcutContext);
  const ref = useRef(handlers);
  useEffect(() => {
    ref.current = handlers;
  });
  useEffect(() => {
    if (!registry || !active) return;
    return registry.register(ref);
  }, [registry, active]);
}
