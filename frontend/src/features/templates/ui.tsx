// Template actions shared across views: Save as Template, run (with the slot form when needed),
// the Ctrl+K palette, and recent templates. Dialogs are mounted once by `TemplateUiProvider`.

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
import { client, problemOf } from "../../api/client";
import type { ImageEntry, Job, Template } from "../../api/types";
import { useNav } from "../../app/nav";
import { useShortcuts } from "../../app/shortcuts";
import { useStudio } from "../../app/studio";
import { useToasts } from "../../app/Toasts";
import { Palette } from "./Palette";
import { RunDialog } from "./RunDialog";
import { SaveTemplateDialog } from "./SaveTemplateDialog";
import {
  bindingsOf,
  noteRecent,
  recalled,
  recentIds,
  runsWithoutInput,
  type SlotValues,
} from "./slots";

type JobListener = (jobs: Job[]) => void;

type Ctx = {
  /** Open the Save as Template dialog for a result or gallery image. */
  saveImage: (image: ImageEntry) => void;
  /** Run now if nothing is missing, else ask for the open slots first. */
  run: (template: Template, opts?: { ask?: boolean }) => void;
  openPalette: () => void;
  /** Ids of the last templates run, newest first. */
  recent: string[];
  /** Called with the jobs of every template run (Generate follows them). */
  onRun: (listener: JobListener | null) => void;
  /** Bumped when a template was saved, so lists reload. */
  rev: number;
};

const UiContext = createContext<Ctx | null>(null);

export function TemplateUiProvider({ children }: { children: ReactNode }) {
  const { dispatch } = useStudio();
  const toasts = useToasts();
  const nav = useNav();
  const [saving, setSaving] = useState<ImageEntry | null>(null);
  const [asking, setAsking] = useState<Template | null>(null);
  const [palette, setPalette] = useState(false);
  const [recent, setRecent] = useState<string[]>(recentIds);
  const [rev, setRev] = useState(0);
  const listener = useRef<JobListener | null>(null);

  const submit = useCallback(
    async (t: Template, values: SlotValues) => {
      try {
        const job = await client.submitJob({
          recipe: t.recipe,
          bindings: bindingsOf(t, values),
          template: t.slug,
        });
        dispatch({ type: "submitted", jobs: [job] });
        listener.current?.([job]);
        setRecent(noteRecent(t.id));
        toasts.push({ kind: "info", message: `Running “${t.name}”.` });
      } catch (e) {
        const p = problemOf(e);
        toasts.problem(
          p,
          p.code === "models.missing"
            ? { label: "Models", run: () => nav.go("models") }
            : undefined,
        );
      }
    },
    [dispatch, toasts, nav],
  );

  const run = useCallback(
    (t: Template, opts?: { ask?: boolean }) => {
      if (!opts?.ask && runsWithoutInput(t, recalled(t.id))) void submit(t, recalled(t.id));
      else setAsking(t);
    },
    [submit],
  );

  const onRun = useCallback((l: JobListener | null) => {
    listener.current = l;
  }, []);
  const openPalette = useCallback(() => setPalette(true), []);
  useShortcuts({ palette: openPalette });

  const value = useMemo<Ctx>(
    () => ({ saveImage: setSaving, run, openPalette, recent, onRun, rev }),
    [run, openPalette, recent, onRun, rev],
  );
  return (
    <UiContext.Provider value={value}>
      {children}
      {saving && (
        <SaveTemplateDialog
          image={saving}
          onClose={() => setSaving(null)}
          onSaved={(t) => {
            setSaving(null);
            setRev((r) => r + 1);
            toasts.push({ kind: "info", message: `Saved template “${t.name}”.` });
          }}
        />
      )}
      {asking && (
        <RunDialog
          template={asking}
          onClose={() => setAsking(null)}
          onRun={(values) => {
            const t = asking;
            setAsking(null);
            void submit(t, values);
          }}
        />
      )}
      {palette && (
        <Palette
          onClose={() => setPalette(false)}
          onPick={(t) => {
            setPalette(false);
            run(t);
          }}
        />
      )}
    </UiContext.Provider>
  );
}

export function useTemplateUi(): Ctx {
  const ctx = useContext(UiContext);
  if (!ctx) throw new Error("useTemplateUi outside TemplateUiProvider");
  return ctx;
}

/** Follow the jobs of template runs started anywhere (the Generate view shows their result). */
export function useTemplateRuns(listener: JobListener): void {
  const { onRun } = useTemplateUi();
  const ref = useRef(listener);
  useEffect(() => {
    ref.current = listener;
  });
  useEffect(() => {
    onRun((jobs) => ref.current(jobs));
    return () => onRun(null);
  }, [onRun]);
}
