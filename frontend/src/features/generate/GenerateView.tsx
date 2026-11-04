// Generate view (R18 Simple mode + Advanced drawer): prompt, an optional photo to start from
// (Phase 17b), style chips, aspect presets, batch count, Generate/Cancel, live progress with an
// ETA, then the result and its follow-ups.

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { client } from "../../api/client";
import type { ImageEntry, Job } from "../../api/types";
import { FINISHED } from "../../api/types";
import { useNav, useRecipeReceiver } from "../../app/nav";
import { useShortcuts } from "../../app/shortcuts";
import { useStudio } from "../../app/studio";
import { useToasts } from "../../app/Toasts";
import { GalleryPicker } from "../../components/GalleryPicker";
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
  PHOTO_PRESETS,
  photoFromImage,
  toRecipe,
  withStyle,
  type FormState,
} from "./form";
import { ResultPanel } from "./ResultPanel";
import { TemplateBar } from "../templates/TemplateBar";
import { useTemplateRuns } from "../templates/ui";

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
  const photoId = useId();
  const [photoOver, setPhotoOver] = useState(false);
  const [uploading, setUploading] = useState(false);

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
  useTemplateRuns(follow);

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

  // "Use as starting photo" from a result or the gallery: load each new hand-off once (during
  // render, as the Inpaint view does).
  const editing = nav.editing;
  const [seenEdit, setSeenEdit] = useState<number | null>(null);
  if (editing?.view === "generate" && editing.at !== seenEdit) {
    setSeenEdit(editing.at);
    setForm((f) => ({ ...f, photo: photoFromImage(editing.image) }));
  }

  const takePhoto = async (file: File | undefined) => {
    if (!file) return;
    setUploading(true);
    try {
      const up = await client.upload(file, "image");
      const url = URL.createObjectURL(file);
      setForm((f) => ({
        ...f,
        photo: { ref: up.id, url, width: up.width, height: up.height, galleryId: null },
      }));
    } catch (e) {
      actions.fail(e);
    } finally {
      setUploading(false);
    }
  };

  const removePhoto = () => {
    if (form.photo?.url.startsWith("blob:")) URL.revokeObjectURL(form.photo.url);
    setForm((f) => ({ ...f, photo: null, denoise: null }));
  };

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
      const submitted = await client.submitJob({
        recipe,
        count: form.count,
        parent: form.photo?.galleryId ?? null,
      });
      setEstimate({
        cold: !state.system?.engine.ready,
        baseline: baselineSeconds(model, aspect, form.count, form.quality),
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
      saveTemplate: shown ? () => actions.saveTemplate(shown) : undefined,
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
        <TemplateBar />
        <div className="field">
          <label htmlFor="prompt">Prompt</label>
          <textarea
            id="prompt"
            ref={prompt}
            rows={4}
            value={form.prompt}
            placeholder={
              form.photo
                ? "Describe the picture you want, e.g. the same house painted green"
                : "Describe the image, e.g. a lighthouse on a rocky coast at dusk"
            }
            onChange={(e) => setForm({ ...form, prompt: e.target.value })}
          />
          {form.photo ? (
            <p className="field-help">
              Describe the picture you want, for example{" "}
              <em>a man in a leather jacket and fedora, adventurer outfit</em>. Higher strength
              changes more but keeps less of the original. To change only one part, use{" "}
              <button type="button" className="btn-link" onClick={() => nav.go("inpaint")}>
                Inpaint
              </button>
              .
            </p>
          ) : (
            <p className="field-help">
              <kbd>Ctrl</kbd>+<kbd>Enter</kbd> generates.
            </p>
          )}
        </div>

        <div
          className={`field dropzone start-photo${photoOver ? " dropzone-over" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setPhotoOver(true);
          }}
          onDragLeave={() => setPhotoOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setPhotoOver(false);
            void takePhoto(e.dataTransfer.files[0]);
          }}
        >
          <label htmlFor={photoId}>Start from a photo (optional)</label>
          {form.photo ? (
            <div className="start-photo-chosen">
              <img
                className="thumb"
                src={form.photo.url}
                alt="Starting photo"
                width={form.photo.width}
                height={form.photo.height}
              />
              <button type="button" className="btn btn-small" onClick={removePhoto}>
                Remove photo
              </button>
              <p className="field-help">
                Describe the picture you want, not the change: "a man in an adventurer outfit,
                fedora and leather jacket", not "dress him as…". Strength Change is the place to
                start.
              </p>
            </div>
          ) : (
            <>
              <input
                id={photoId}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                disabled={uploading}
                onChange={(e) => {
                  void takePhoto(e.target.files?.[0]);
                  e.target.value = "";
                }}
              />
              <GalleryPicker
                label="Start from a photo"
                disabled={uploading}
                onPick={(img) => setForm((f) => ({ ...f, photo: photoFromImage(img) }))}
              />
              <p className="field-help" aria-live="polite">
                {uploading
                  ? "Uploading…"
                  : "Choose a photo or drop it here, and P11 re-renders it following your prompt."}
              </p>
            </>
          )}
        </div>

        {form.photo && (
          <fieldset className="field">
            <legend>Strength</legend>
            <div className="chips">
              {PHOTO_PRESETS.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className="chip"
                  aria-pressed={form.denoise === null && form.strength === p.id}
                  onClick={() => setForm({ ...form, strength: p.id, denoise: null })}
                >
                  {p.label}
                </button>
              ))}
            </div>
            <p className="field-help">
              {form.denoise !== null
                ? `Custom strength ${form.denoise.toFixed(2)} (Advanced).`
                : PHOTO_PRESETS.find((p) => p.id === form.strength)?.about}
            </p>
          </fieldset>
        )}

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

        <fieldset className="field" disabled={!!form.photo}>
          <legend>Size</legend>
          <div className="chips">
            {aspects.map((a) => (
              <button
                key={a.id}
                type="button"
                className="chip"
                aria-pressed={!form.photo && aspectId === a.id}
                onClick={() => setForm({ ...form, aspect: a.id })}
              >
                {a.label}
              </button>
            ))}
          </div>
          {form.photo && (
            <p className="field-help">
              The picture keeps the photo&apos;s own shape ({form.photo.width} × {form.photo.height}
              ).
            </p>
          )}
        </fieldset>

        {(() => {
          const chosen = aspects.find((a) => a.id === aspectId);
          if (!form.photo && (!chosen || chosen.quality_chain === chosen.chain)) return null;
          return (
            <fieldset className="field">
              <legend>Upscale quality</legend>
              <div className="chips">
                <button
                  type="button"
                  className="chip"
                  aria-pressed={!form.quality}
                  onClick={() => setForm({ ...form, quality: false })}
                >
                  Speed
                </button>
                <button
                  type="button"
                  className="chip"
                  aria-pressed={form.quality}
                  onClick={() => setForm({ ...form, quality: true })}
                >
                  Quality
                </button>
              </div>
              <p className="field-help">
                {form.quality
                  ? "A refinement pass adds detail after the model upscale (slower)."
                  : "Model upscale only: crisp and fast. Pick Quality for more detail."}
              </p>
            </fieldset>
          );
        })()}

        <div className="row">
          <label htmlFor="count">Number of images</label>
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
              <p>
                Or start from a photo: add one under the prompt and describe what it should become.
              </p>
            </section>
          )
        )}
      </div>
    </div>
  );
}
