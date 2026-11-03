// Which view is shown, and hand-offs between views (gallery "open as recipe" → Generate).

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { ImageEntry, RunRecord } from "../api/types";

export type View =
  "generate" | "gallery" | "templates" | "inpaint" | "background" | "face" | "video" | "models";

export const VIEWS: { id: View; label: string; phase?: string; about: string }[] = [
  { id: "generate", label: "Generate", about: "Text to image." },
  { id: "gallery", label: "Gallery", about: "Everything you made." },
  { id: "templates", label: "Templates", about: "Saved one-click recipes." },
  { id: "inpaint", label: "Inpaint", about: "Repaint part of an image." },
  { id: "background", label: "Background", phase: "11", about: "Swap the background." },
  { id: "face", label: "Face & Pose", phase: "12", about: "Face swap, pose and reference." },
  { id: "video", label: "Video", phase: "13", about: "Face swap in short clips." },
  { id: "models", label: "Models", phase: "14", about: "Install and switch models." },
];

export function phaseOf(view: View): string | undefined {
  return VIEWS.find((v) => v.id === view)?.phase;
}

type RecipeListener = (record: RunRecord) => void;

type Ctx = {
  view: View;
  go: (view: View) => void;
  /** Load a run record into the Generate form and show it ("open as recipe"). */
  openRecipe: (record: RunRecord) => void;
  /** The Generate view registers the receiver of `openRecipe`. */
  onRecipe: (listener: RecipeListener | null) => void;
  /** The image an editing view (Inpaint, later Background/Face) was opened with. */
  editing: { view: View; image: ImageEntry; at: number } | null;
  /** Open `image` in an editing view. */
  edit: (view: View, image: ImageEntry) => void;
};

const NavContext = createContext<Ctx | null>(null);

export function NavProvider({
  children,
  initial = "generate",
}: {
  children: ReactNode;
  initial?: View;
}) {
  const [view, setView] = useState<View>(initial);
  const listener = useRef<RecipeListener | null>(null);
  const [editing, setEditing] = useState<Ctx["editing"]>(null);
  const edit = useCallback((target: View, image: ImageEntry) => {
    setEditing({ view: target, image, at: Date.now() });
    setView(target);
  }, []);
  const openRecipe = useCallback((record: RunRecord) => {
    listener.current?.(record);
    setView("generate");
  }, []);
  const onRecipe = useCallback((l: RecipeListener | null) => {
    listener.current = l;
  }, []);
  const value = useMemo(
    () => ({ view, go: setView, openRecipe, onRecipe, editing, edit }),
    [view, openRecipe, onRecipe, editing, edit],
  );
  return <NavContext.Provider value={value}>{children}</NavContext.Provider>;
}

/** Receive "open as recipe" hand-offs while mounted. */
export function useRecipeReceiver(receive: RecipeListener): void {
  const { onRecipe } = useNav();
  const ref = useRef(receive);
  useEffect(() => {
    ref.current = receive;
  });
  useEffect(() => {
    onRecipe((r) => ref.current(r));
    return () => onRecipe(null);
  }, [onRecipe]);
}

export function useNav(): Ctx {
  const ctx = useContext(NavContext);
  if (!ctx) throw new Error("useNav outside NavProvider");
  return ctx;
}
