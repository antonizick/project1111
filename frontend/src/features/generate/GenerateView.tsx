// Generate view (R18 Simple mode + Advanced drawer): prompt, style chips, aspect presets, batch
// count, Generate/Cancel, live progress with an ETA, then the result and its follow-ups.

import { useCallback, useEffect, useRef, useState } from "react";
import { client } from "../../api/client";
import type { ImageEntry, Job } from "../../api/types";
import { FINISHED } from "../../api/types";
import { useNav, useRecipeReceiver } from "../../app/nav";
import { useShortcuts } from "../../app/shortcuts";
import { useStudio } from "../../app/studio";
import { useToasts } from "../../app/Toasts";
import { useImageActions } from "../actions";
import { AdvancedDrawer } from "./AdvancedDrawer";
import { baselineSeconds, formatSeconds, remainingSeconds } from "./eta";
import {
  clampCount,
  effectiveAspect,
  effectiveModel,
  fromRecord,
  initialForm,
  MAX_BATCH,
  newRecipeId,
  toRecipe,
  withStyle,
  type FormState,
} from "./form";
import { ResultPanel } from "./ResultPanel";

export function stageLabel(title: string | null | undefined, job: Job): string {
  if (job.state === "queued") return "Waiting in the queue";
  if (job.state === "paused") return job.note ?? "Paused";
  if (title === "base") return "Generating";
  if (title === "hires") return "Refining";
  if (title) return title.charAt(0).toUpperCase() + title.slice(1);
  return "Starting";
}

export function GenerateView({ active }: { active: boolean }) {
  const { state, dispatch } = useStudio();
  const toasts = useToasts();
  const nav = useNav();
  const [form, setForm] = useState<FormState>(initialForm);
  const [advanced, setAdvanced] = useState(false);
  /** Jobs started from this view, oldest first; the newest one is followed. */
  const [followed, setFollowed] = useState<string[]>([]);
  const [pick, setPick] = useState<{ job: string; index: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [estimate, setEstimate] = useState({ cold: false, baseline: 0 });
  const [now, setNow] = useState(() => Date.now());
  const prompt = useRef<HTMLTextAreaElement>(null);

  const jobId = followed[followed.length - 1] ?? null;
  const job = jobId ? state.jobs[jobId] : undefined;
  const running = !!job && !FINISHED.has(job.state);
  // The result shown is the newest followed job that finished with images.
  const resultJob = [...followed]
    .reverse()
    .map((id) => state.jobs[id])
    .find((j) => j?.state === "done" && j.images.length > 0);
  const images = (resultJob?.images ?? [])
    .map((id) => state.images[id])
    .filter((i): i is ImageEntry => i !== undefined);
  const index = pick && pick.job === resultJob?.id ? pick.index : 0;
  const setIndex = (i: number) => resultJob && setPick({ job: resultJob.id, index: i });
  const shown = images[Math.min(index, images.length - 1)];

  const follow = useCallback((jobs: Job[]) => {
    setFollowed((f) => [...f, ...jobs.map((j) => j.id)].slice(-20));
  }, []);
  const actions = useImageActions(follow);

  // "Open as recipe" from the gallery.
  useRecipeReceiver((record) => {
    const loaded = fromRecord(record);
    if (!loaded) {
      toasts.push({ kind: "info", message: "That image has no generate step to load." });
      return;
    }
    setForm(loaded.form);
    setAdvanced(true);
    toasts.push({
      kind: "info",
      message: loaded.partial
        ? "Loaded the generate settings; the other steps of this recipe were left out."
        : "Settings loaded. The seed is locked so Generate reproduces the image.",
    });
  });

  // Fetch result entries the event stream did not deliver; report failures once.
  const jobState = job?.state;
  useEffect(() => {
    if (!job) return;
    if (job.state === "done")
      for (const id of job.images)
        if (!state.images[id])
          client
            .image(id)
            .then((image) => dispatch({ type: "image", image }))
            .catch(() => undefined);
    if (job.state === "failed" && job.error) {
      const err = job.error;
      toasts.problem(
        err,
        err.code === "models.missing"
          ? { label: "Models", run: () => nav.go("models") }
          : undefined,
      );
    }
    // Only react to state changes of the followed job.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, jobState]);

  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [running]);

  const generate = async () => {
    if (busy || running) return;
    if (!form.prompt.trim()) {
      toasts.push({ kind: "info", message: "Type what you want to see first." });
      prompt.current?.focus();
      return;
    }
    const model = effectiveModel(form, state.presets);
    const aspect = effectiveAspect(form, state.presets);
    setBusy(true);
    try {
      const recipe = toRecipe(form, { id: newRecipeId(), now: new Date() });
      const submitted = await client.submitJob({ recipe, count: form.count });
      setEstimate({
        cold: !state.system?.engine.ready,
        baseline: baselineSeconds(model, aspect, form.count),
      });
      dispatch({ type: "submitted", jobs: [submitted], model });
      follow([submitted]);
    } catch (e) {
      actions.fail(e);
    } finally {
      setBusy(false);
    }
  };

  const cancel = () => {
    if (jobId && running) client.cancelJob(jobId).catch(actions.fail);
  };

  useShortcuts(
    {
      generate: () => void generate(),
      escape: running ? cancel : undefined,
      variation: shown ? () => actions.variations(shown, "seed", form.count) : undefined,
      saveTemplate: () => actions.later("template"),
    },
    active,
  );

  const progress = jobId ? state.progress[jobId] : undefined;
  const preview = jobId ? state.previews[jobId] : undefined;
  // A job's updated_at is written at each state change, so while running it is the start time.
  const elapsed =
    job?.state === "running" ? Math.max(0, (now - Date.parse(job.updated_at)) / 1000) : 0;
  const eta =
    job && job.state === "running"
      ? formatSeconds(
          remainingSeconds(job.progress, elapsed, estimate.baseline || 30, estimate.cold),
        )
      : null;
  const aspectId = effectiveAspect(form, state.presets);
  const styles = state.presets?.styles ?? [];
  const aspects = (state.presets?.aspects ?? []).filter(
    (a) =>
      a.id.startsWith("16:9") || a.id === "1:1-1024" || a.id === "avatar-4:5" || a.id === aspectId,
  );

  return (
    <div className="generate" hidden={!active}>
      <form
        className="generate-form"
        aria-label="Generate"
        onSubmit={(e) => {
          e.preventDefault();
          void generate();
        }}
      >
        <div className="field">
          <label htmlFor="prompt">Prompt</label>
          <textarea
            id="prompt"
            ref={prompt}
            rows={4}
            value={form.prompt}
            placeholder="Describe the image, e.g. a lighthouse on a rocky coast at dusk"
            onChange={(e) => setForm({ ...form, prompt: e.target.value })}
          />
          <p className="field-help">
            <kbd>Ctrl</kbd>+<kbd>Enter</kbd> generates.
          </p>
        </div>

        <fieldset className="field">
          <legend>Style</legend>
          <div className="chips">
            {styles.map((s) => (
              <button
                key={s.id}
                type="button"
                className="chip"
                aria-pressed={form.style === s.id}
                onClick={() => setForm(withStyle(form, s.id, state.presets))}
              >
                {s.label}
              </button>
            ))}
          </div>
        </fieldset>

        <fieldset className="field">
          <legend>Size</legend>
          <div className="chips">
            {aspects.map((a) => (
              <button
                key={a.id}
                type="button"
                className="chip"
                aria-pressed={aspectId === a.id}
                onClick={() => setForm({ ...form, aspect: a.id })}
              >
                {a.label}
              </button>
            ))}
          </div>
        </fieldset>

        <div className="row">
          <label htmlFor="count">Images</label>
          <input
            id="count"
            type="number"
            min={1}
            max={MAX_BATCH}
            value={form.count}
            onChange={(e) => setForm({ ...form, count: clampCount(Number(e.target.value)) })}
          />
          <span className="grow" />
          {running ? (
            <button type="button" className="btn btn-danger" onClick={cancel}>
              Cancel <kbd>Esc</kbd>
            </button>
          ) : (
            <button type="submit" className="btn btn-primary btn-large" disabled={busy}>
              Generate
            </button>
          )}
        </div>

        <button
          type="button"
          className="btn btn-ghost"
          aria-expanded={advanced}
          aria-controls="advanced"
          onClick={() => setAdvanced(!advanced)}
        >
          {advanced ? "▾ Hide advanced" : "▸ Advanced"}
        </button>
        <div id="advanced" hidden={!advanced}>
          {advanced && (
            <AdvancedDrawer
              form={form}
              setForm={setForm}
              presets={state.presets}
              models={state.models}
              lastSeed={shown?.seed ?? null}
            />
          )}
        </div>
      </form>

      <div className="stage">
        {job && running && (
          <section className="progress" aria-label="Progress">
            <p className="progress-label" aria-live="polite">
              {stageLabel(progress?.title, job)}
              {progress && progress.runs > 1
                ? ` · image ${progress.run + 1} of ${progress.runs}`
                : ""}
              {progress?.step !== undefined && progress.total
                ? ` · step ${progress.step}/${progress.total}`
                : ""}
            </p>
            <progress max={1} value={job.progress} aria-label="Job progress" />
            <p className="progress-sub">
              {Math.round(job.progress * 100)} %{eta ? ` · ${eta}` : ""}
            </p>
            {job.note && <p className="note">{job.note}</p>}
            {preview && <img className="preview" src={preview} alt="Live preview" />}
          </section>
        )}
        {images.length > 0 ? (
          <ResultPanel
            images={images}
            index={index}
            setIndex={setIndex}
            actions={actions}
            batch={form.count}
          />
        ) : (
          !running && (
            <section className="empty" aria-label="Getting started">
              <h2>Make your first image</h2>
              <p>
                Type what you want to see, pick a style and a size, then press{" "}
                <strong>Generate</strong> (or <kbd>Ctrl</kbd>+<kbd>Enter</kbd>).
              </p>
            </section>
          )
        )}
      </div>
    </div>
  );
}
