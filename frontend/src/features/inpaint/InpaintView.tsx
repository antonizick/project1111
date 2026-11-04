// Inpaint view (Phase 10): open a result, a gallery image or an uploaded photo, paint a mask, say
// what should be there, pick Subtle fix / Change / Replace and Apply. The result is a child of the
// image in the gallery and can be edited again ("Keep editing") or saved as a template.

import { useEffect, useId, useRef, useState } from "react";
import { client } from "../../api/client";
import type { ImageEntry, Job } from "../../api/types";
import { FINISHED } from "../../api/types";
import { useNav } from "../../app/nav";
import { useShortcuts } from "../../app/shortcuts";
import { useStudio } from "../../app/studio";
import { useToasts } from "../../app/Toasts";
import { GalleryPicker } from "../../components/GalleryPicker";
import { useImageActions } from "../actions";
import { newRecipeId } from "../generate/form";
import { ImageActions } from "../generate/ResultPanel";
import { stageLabel } from "../generate/GenerateView";
import { MaskEditor, type MaskEditorHandle } from "../mask-editor/MaskEditor";
import {
  initialInpaint,
  inpaintRecipe,
  MASK_SLOT,
  PRESETS,
  type InpaintForm,
  type Source,
} from "./recipe";

export function InpaintView({ active }: { active: boolean }) {
  const { state, dispatch } = useStudio();
  const nav = useNav();
  const toasts = useToasts();
  const id = useId();
  const editor = useRef<MaskEditorHandle>(null);
  const [source, setSource] = useState<Source | null>(null);
  const [form, setForm] = useState<InpaintForm>(initialInpaint);
  const [hasMask, setHasMask] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [busy, setBusy] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const actions = useImageActions((jobs: Job[]) => setJobId(jobs[0]?.id ?? null));

  const checkpoint = (model: string | null) =>
    model && (state.models ?? []).some((m) => m.id === model && m.kind === "checkpoint")
      ? model
      : null;

  const fromImage = (img: ImageEntry) => {
    setSource({
      kind: "gallery",
      id: img.id,
      url: img.url,
      width: img.width ?? 1024,
      height: img.height ?? 1024,
      model: img.model,
    });
    setForm((f) => ({ ...initialInpaint(img.prompt), preset: f.preset, crop: f.crop }));
    setJobId(null);
  };

  // Opened from a result panel or the gallery: load each new hand-off once (during render, the
  // React pattern for state derived from a changed prop).
  const editing = nav.editing;
  const [seen, setSeen] = useState<number | null>(null);
  if (editing?.view === "inpaint" && editing.at !== seen) {
    setSeen(editing.at);
    fromImage(editing.image);
  }

  const uploadPhoto = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    try {
      const up = await client.upload(file, "image");
      setSource({
        kind: "upload",
        id: up.id,
        url: URL.createObjectURL(file),
        width: up.width,
        height: up.height,
      });
      setForm(initialInpaint(""));
      setJobId(null);
    } catch (e) {
      actions.fail(e);
    } finally {
      setBusy(false);
    }
  };

  const job = jobId ? state.jobs[jobId] : undefined;
  const running = !!job && !FINISHED.has(job.state);
  const result =
    job?.state === "done" && job.images[0] !== undefined ? state.images[job.images[0]] : undefined;

  // Fetch the result entry if the event stream missed it; show failures once.
  const jobState = job?.state;
  useEffect(() => {
    if (!job) return;
    if (job.state === "done")
      for (const i of job.images)
        if (!state.images[i])
          client
            .image(i)
            .then((image) => dispatch({ type: "image", image }))
            .catch(() => undefined);
    if (job.state === "failed" && job.error) toasts.problem(job.error);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, jobState]);

  const apply = async () => {
    if (!source || busy || running) return;
    setBusy(true);
    try {
      const blob = await editor.current?.exportMask();
      if (!blob) {
        toasts.push({
          kind: "info",
          message: "Paint over the part of the image you want to change first.",
        });
        return;
      }
      const mask = await client.upload(blob, "mask");
      const src =
        source.kind === "gallery" ? { ...source, model: checkpoint(source.model) } : source;
      const submitted = await client.submitJob({
        recipe: inpaintRecipe(form, src, { id: newRecipeId(), now: new Date() }),
        bindings: { [MASK_SLOT]: { ref: mask.id } },
        parent: source.kind === "gallery" ? source.id : null,
      });
      dispatch({ type: "submitted", jobs: [submitted] });
      setJobId(submitted.id);
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
      generate: () => void apply(),
      escape: running ? cancel : undefined,
      saveTemplate: result ? () => actions.saveTemplate(result) : undefined,
    },
    active,
  );

  const progress = jobId ? state.progress[jobId] : undefined;
  const set = (patch: Partial<InpaintForm>) => setForm((f) => ({ ...f, ...patch }));
  const presetInfo = PRESETS.find((p) => p.id === form.preset);

  return (
    <div className="inpaint" hidden={!active}>
      <form
        className="inpaint-form"
        aria-label="Inpaint"
        onSubmit={(e) => {
          e.preventDefault();
          void apply();
        }}
      >
        <div className="field">
          <label htmlFor={`${id}-photo`}>Upload photo</label>
          <input
            id={`${id}-photo`}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            disabled={busy}
            onChange={(e) => void uploadPhoto(e.target.files?.[0])}
          />
          <GalleryPicker label="Upload photo" disabled={busy} onPick={fromImage} />
          <p className="field-help">
            Or use <strong>Inpaint</strong> on a result or a gallery image.
          </p>
        </div>
        <div className="field">
          <label htmlFor={`${id}-prompt`}>What should be there (optional)</label>
          <textarea
            id={`${id}-prompt`}
            rows={3}
            value={form.prompt}
            placeholder="e.g. a red wool scarf"
            onChange={(e) => set({ prompt: e.target.value })}
          />
        </div>
        <fieldset className="field">
          <legend>Strength</legend>
          <div className="chips">
            {PRESETS.map((p) => (
              <button
                key={p.id}
                type="button"
                className="chip"
                aria-pressed={form.denoise === null && form.preset === p.id}
                onClick={() => set({ preset: p.id, denoise: null })}
              >
                {p.label}
              </button>
            ))}
          </div>
          <p className="field-help">
            {form.denoise === null ? presetInfo?.about : `Custom strength ${form.denoise}.`}
          </p>
        </fieldset>
        <label className="check">
          <input
            type="checkbox"
            checked={form.crop}
            onChange={(e) => set({ crop: e.target.checked })}
          />
          Only masked area at full resolution
        </label>
        <p className="field-help">
          On suits small fixes such as a hand or a face. Off suits anything large, such as clothes.
        </p>
        <div className="row">
          <span className="grow" />
          {running ? (
            <button type="button" className="btn btn-danger" onClick={cancel}>
              Cancel <kbd>Esc</kbd>
            </button>
          ) : (
            <button
              type="submit"
              className="btn btn-primary btn-large"
              disabled={!source || busy || !hasMask}
            >
              Apply
            </button>
          )}
        </div>
        <button
          type="button"
          className="btn btn-ghost"
          aria-expanded={advanced}
          aria-controls={`${id}-advanced`}
          onClick={() => setAdvanced(!advanced)}
        >
          {advanced ? "▾ Hide advanced" : "▸ Advanced"}
        </button>
        <div id={`${id}-advanced`} className="advanced" hidden={!advanced}>
          <label className="slider">
            <span>Denoise {form.denoise === null ? "(preset)" : form.denoise.toFixed(2)}</span>
            <input
              type="range"
              min={5}
              max={100}
              value={Math.round((form.denoise ?? 0.6) * 100)}
              onChange={(e) => set({ denoise: Number(e.target.value) / 100 })}
            />
          </label>
          <div className="field">
            <label htmlFor={`${id}-blur`}>Mask blur (px)</label>
            <input
              id={`${id}-blur`}
              type="number"
              min={0}
              max={128}
              value={form.blur}
              onChange={(e) => set({ blur: clamp(Number(e.target.value), 0, 128) })}
            />
          </div>
          <div className="field">
            <label htmlFor={`${id}-padding`}>Padding around the mask (px)</label>
            <input
              id={`${id}-padding`}
              type="number"
              min={0}
              max={1024}
              value={form.padding}
              onChange={(e) => set({ padding: clamp(Number(e.target.value), 0, 1024) })}
            />
          </div>
          <div className="field">
            <label htmlFor={`${id}-steps`}>Steps (empty = model default)</label>
            <input
              id={`${id}-steps`}
              type="number"
              min={1}
              max={200}
              value={form.steps ?? ""}
              onChange={(e) =>
                set({ steps: e.target.value ? clamp(Number(e.target.value), 1, 200) : null })
              }
            />
          </div>
          <div className="field">
            <label htmlFor={`${id}-seed`}>Seed (empty = random)</label>
            <input
              id={`${id}-seed`}
              type="number"
              min={0}
              value={form.seed ?? ""}
              onChange={(e) => set({ seed: e.target.value ? Number(e.target.value) : null })}
            />
          </div>
        </div>
      </form>

      <div className="stage">
        {source ? (
          <MaskEditor
            key={source.url}
            ref={editor}
            src={source.url}
            width={source.width}
            height={source.height}
            feather={form.blur}
            onFeather={(blur) => set({ blur })}
            onChange={setHasMask}
            active={active}
          />
        ) : (
          <section className="empty" aria-label="Getting started">
            <h2>Fix or change part of an image</h2>
            <p>
              Press <strong>Inpaint</strong> on a result or a gallery image, or upload a photo. Then
              paint over the part to change and press <strong>Apply</strong>.
            </p>
          </section>
        )}
        {job && running && (
          <section className="progress" aria-label="Progress">
            <p className="progress-label" aria-live="polite">
              {stageLabel(progress?.title, job)}
              {progress?.step !== undefined && progress.total
                ? ` · step ${progress.step}/${progress.total}`
                : ""}
            </p>
            <progress max={1} value={job.progress} aria-label="Job progress" />
          </section>
        )}
        {result && (
          <section className="result" aria-label="Inpaint result">
            <img className="result-image" src={result.url} alt={`Inpainted: ${result.prompt}`} />
            <div className="row">
              <button type="button" className="btn" onClick={() => fromImage(result)}>
                Keep editing this result
              </button>
            </div>
            <ImageActions image={result} actions={actions} />
          </section>
        )}
      </div>
    </div>
  );
}

function clamp(v: number, lo: number, hi: number): number {
  return Number.isFinite(v) ? Math.min(hi, Math.max(lo, Math.round(v))) : lo;
}
