// Background view (Phase 11): open a result, a gallery image or an uploaded photo, P11 finds the
// subject (Refine opens the mask editor on the auto-mask), pick a photo / description / colour
// background, tune the blend and press Replace Background. The stage previews the composite
// through /api/background/preview, so it is what Apply saves. The result is a child of the image
// in the gallery and can be edited again or saved as a template.

import { useEffect, useId, useRef, useState } from "react";
import { client } from "../../api/client";
import type { ImageEntry, Job } from "../../api/types";
import { FINISHED } from "../../api/types";
import { useNav } from "../../app/nav";
import { useShortcuts } from "../../app/shortcuts";
import { useStudio } from "../../app/studio";
import { useToasts } from "../../app/Toasts";
import { useImageActions } from "../actions";
import { newRecipeId } from "../generate/form";
import { stageLabel } from "../generate/GenerateView";
import { ImageActions } from "../generate/ResultPanel";
import { MaskEditor, type MaskEditorHandle } from "../mask-editor/MaskEditor";
import {
  BACKGROUND_SLOT,
  MASK_SLOT,
  backgroundRecipe,
  describeRecipe,
  initialBackground,
  nearestAspect,
  type BackgroundChoice,
  type BackgroundForm,
  type Harmonize,
  type Source,
} from "./recipe";

const HARMONIZE: { id: Harmonize; label: string; about: string }[] = [
  { id: "off", label: "Off", about: "Keep the subject's own light." },
  { id: "light", label: "Light", about: "Match the light near the edge (default)." },
  { id: "strong", label: "Strong", about: "Match the light harder across the subject." },
];

export function BackgroundView({ active }: { active: boolean }) {
  const { state, dispatch } = useStudio();
  const nav = useNav();
  const toasts = useToasts();
  const id = useId();
  const editor = useRef<MaskEditorHandle>(null);
  const [source, setSource] = useState<Source | null>(null);
  const [form, setForm] = useState<BackgroundForm>(initialBackground);
  const [choice, setChoice] = useState<BackgroundChoice | null>(null);
  const [maskUrl, setMaskUrl] = useState<string | null>(null);
  const [maskRef, setMaskRef] = useState<string | null>(null);
  const [maskLoading, setMaskLoading] = useState(false);
  const [refining, setRefining] = useState(false);
  const [hasMask, setHasMask] = useState(false);
  const [showMask, setShowMask] = useState(true);
  const [preview, setPreview] = useState<string | null>(null);
  const [describe, setDescribe] = useState("");
  const [busy, setBusy] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const actions = useImageActions((jobs: Job[]) => setJobId(jobs[0]?.id ?? null));
  const previewSeq = useRef(0);

  const set = (patch: Partial<BackgroundForm>) => setForm((f) => ({ ...f, ...patch }));

  /** Run the auto-mask for a subject and upload it for previews and the job. */
  const autoMask = async (src: Source) => {
    setMaskLoading(true);
    setMaskUrl(null);
    setMaskRef(null);
    setHasMask(false);
    try {
      const { blob } = await client.backgroundMask(src.ref);
      const url = URL.createObjectURL(blob);
      const upload = await client.upload(blob, "mask");
      setMaskUrl(url);
      setMaskRef(upload.id);
      setHasMask(true);
    } catch (e) {
      actions.fail(e);
    } finally {
      setMaskLoading(false);
    }
  };

  const fromImage = (img: ImageEntry) => {
    const src: Source = {
      kind: "gallery",
      id: img.id,
      ref: `gallery/${img.id}`,
      url: img.url,
      width: img.width ?? 1024,
      height: img.height ?? 1024,
    };
    setSource(src);
    setChoice(null);
    setPreview(null);
    setRefining(false);
    setJobId(null);
    void autoMask(src);
  };

  // Opened from a result panel or the gallery: load each new hand-off once.
  const editing = nav.editing;
  const [seen, setSeen] = useState<number | null>(null);
  if (editing?.view === "background" && editing.at !== seen) {
    setSeen(editing.at);
    fromImage(editing.image);
  }

  /** The photo being edited: uploaded here or handed off from a result. */
  const uploadSubject = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    try {
      const up = await client.upload(file, "image");
      const src: Source = {
        kind: "upload",
        id: up.id,
        ref: up.id,
        url: URL.createObjectURL(file),
        width: up.width,
        height: up.height,
      };
      setSource(src);
      setChoice(null);
      setPreview(null);
      setRefining(false);
      setJobId(null);
      void autoMask(src);
    } catch (e) {
      actions.fail(e);
    } finally {
      setBusy(false);
    }
  };

  /** The background photo being put behind the subject. */
  const uploadBackground = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    try {
      const up = await client.upload(file, "image");
      setChoice({ kind: "photo", ref: up.id, url: URL.createObjectURL(file) });
    } catch (e) {
      actions.fail(e);
    } finally {
      setBusy(false);
    }
  };

  const describeBackground = async () => {
    if (!source || !describe.trim() || busy) return;
    setBusy(true);
    try {
      const r = describeRecipe(
        describe.trim(),
        nearestAspect(state.presets, source.width, source.height),
        { id: newRecipeId(), now: new Date() },
      );
      const job = await client.submitJob({ recipe: r, parent: null });
      dispatch({ type: "submitted", jobs: [job] });
      const done = await waitForImages(job.id);
      const bg = done[0];
      if (bg) setChoice({ kind: "gallery", ref: `gallery/${bg.id}`, url: bg.url });
    } catch (e) {
      actions.fail(e);
    } finally {
      setBusy(false);
    }
  };

  /** Poll a job and resolve with its finished images (for Describe). */
  const waitForImages = (id: string): Promise<ImageEntry[]> =>
    new Promise((resolve, reject) => {
      const timer = setInterval(() => {
        client
          .job(id)
          .then((job) => {
            if (!FINISHED.has(job.state)) return;
            clearInterval(timer);
            if (job.state !== "done") {
              reject(new Error(job.error?.message ?? "The background could not be generated."));
              return;
            }
            Promise.all(job.images.map((i) => client.image(i))).then(resolve, reject);
          })
          .catch(() => undefined);
      }, 250);
    });

  // Live preview through the server (same pipeline Apply runs), debounced per change.
  const choiceRef = choice;
  const formRef = form;
  useEffect(() => {
    if (!source || !maskRef || refining) return;
    const seq = ++previewSeq.current;
    const timer = setTimeout(() => {
      const body = {
        image: { ref: source.ref },
        background: choiceRef && choiceRef.kind !== "colour" ? { ref: choiceRef.ref } : null,
        background_colour:
          choiceRef && choiceRef.kind === "colour"
            ? choiceRef.transparent
              ? "#00000000"
              : choiceRef.colour
            : null,
        mask: { ref: maskRef },
        colour_match: formRef.colourMatch,
        feather_px: formRef.feather,
        fit: formRef.fit,
        background_x: formRef.backgroundX,
        background_y: formRef.backgroundY,
        subject_scale: formRef.subjectScale,
        subject_x: formRef.subjectX,
        subject_y: formRef.subjectY,
        shadow: formRef.shadow,
      };
      client
        .backgroundPreview(body)
        .then(({ blob }) => {
          if (previewSeq.current !== seq) return;
          setPreview((old) => {
            if (old) URL.revokeObjectURL(old);
            return URL.createObjectURL(blob);
          });
        })
        .catch(() => undefined);
    }, 250);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, maskRef, choice, form, refining]);

  const job = jobId ? state.jobs[jobId] : undefined;
  const running = !!job && !FINISHED.has(job.state);
  const result =
    job?.state === "done" && job.images[0] !== undefined ? state.images[job.images[0]] : undefined;

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
  }, [jobId, job?.state]);

  const apply = async () => {
    if (!source || !maskRef || !choice || busy || running) return;
    setBusy(true);
    try {
      const bindings: Record<string, unknown> = { [MASK_SLOT]: { ref: maskRef } };
      if (choice.kind !== "colour") bindings[BACKGROUND_SLOT] = { ref: choice.ref };
      const submitted = await client.submitJob({
        recipe: backgroundRecipe(form, source, choice, {
          id: newRecipeId(),
          now: new Date(),
          seed: null,
        }),
        bindings,
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

  const keepRefined = async () => {
    const blob = await editor.current?.exportMask();
    if (!blob) {
      toasts.push({ kind: "info", message: "Paint over the subject first." });
      return;
    }
    setRefining(false);
    setMaskLoading(true);
    try {
      const upload = await client.upload(blob, "mask");
      setMaskUrl(URL.createObjectURL(blob));
      setMaskRef(upload.id);
      setHasMask(true);
    } catch (e) {
      actions.fail(e);
    } finally {
      setMaskLoading(false);
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

  return (
    <div className="inpaint background" hidden={!active}>
      <form
        className="inpaint-form"
        aria-label="Background"
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
            onChange={(e) => void uploadSubject(e.target.files?.[0])}
          />
          <p className="field-help">
            Or press <strong>Background</strong> on a result or a gallery image.
          </p>
        </div>

        <fieldset className="field">
          <legend>New background</legend>
          <div className="chips">
            <label className="chip">
              Photo…
              <input
                type="file"
                aria-label="Background photo"
                accept="image/png,image/jpeg,image/webp"
                hidden
                disabled={busy}
                onChange={(e) => void uploadBackground(e.target.files?.[0])}
              />
            </label>
            <button
              type="button"
              className="chip"
              aria-pressed={choice?.kind === "colour"}
              onClick={() => setChoice({ kind: "colour", colour: "#101418", transparent: true })}
            >
              Colour / transparent
            </button>
          </div>
          {choice?.kind === "colour" && (
            <div className="row">
              <label className="check">
                <input
                  type="checkbox"
                  checked={choice.transparent}
                  onChange={(e) => setChoice({ ...choice, transparent: e.target.checked })}
                />
                Transparent (PNG with alpha)
              </label>
              {!choice.transparent && (
                <input
                  type="color"
                  aria-label="Background colour"
                  value={choice.colour}
                  onChange={(e) => setChoice({ ...choice, colour: e.target.value })}
                />
              )}
            </div>
          )}
          <div className="row">
            <input
              id={`${id}-describe`}
              type="text"
              placeholder="or describe one: a sunny beach"
              aria-label="Describe the background"
              value={describe}
              disabled={busy}
              onChange={(e) => setDescribe(e.target.value)}
            />
            <button
              type="button"
              className="btn"
              disabled={busy || !describe.trim()}
              onClick={() => void describeBackground()}
            >
              Generate
            </button>
          </div>
          {choice && choice.kind !== "colour" && (
            <img className="background-thumb" src={choice.url} alt="Background" />
          )}
        </fieldset>

        <fieldset className="field">
          <legend>Blend</legend>
          <div className="chips">
            {HARMONIZE.map((h) => (
              <button
                key={h.id}
                type="button"
                className="chip"
                aria-pressed={form.harmonize === h.id}
                onClick={() => set({ harmonize: h.id })}
              >
                {h.label}
              </button>
            ))}
          </div>
          <p className="field-help">
            {HARMONIZE.find((h) => h.id === form.harmonize)?.about} Colour match{" "}
            {form.colourMatch ? "on" : "off"}.
          </p>
          <label className="check">
            <input
              type="checkbox"
              checked={form.colourMatch}
              onChange={(e) => set({ colourMatch: e.target.checked })}
            />
            Match the colours of the background
          </label>
          <label className="slider">
            <span>Edge feather {form.feather} px</span>
            <input
              type="range"
              min={0}
              max={128}
              value={form.feather}
              onChange={(e) => set({ feather: Number(e.target.value) })}
            />
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={form.shadow}
              onChange={(e) => set({ shadow: e.target.checked })}
            />
            Drop shadow
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={showMask}
              onChange={(e) => setShowMask(e.target.checked)}
            />
            Show mask overlay
          </label>
        </fieldset>

        <div className="row">
          <button
            type="button"
            className="btn"
            disabled={!source || !hasMask || refining}
            onClick={() => setRefining(true)}
          >
            Refine mask
          </button>
          <span className="grow" />
          {running ? (
            <button type="button" className="btn btn-danger" onClick={cancel}>
              Cancel <kbd>Esc</kbd>
            </button>
          ) : (
            <button
              type="submit"
              className="btn btn-primary btn-large"
              disabled={!source || !hasMask || !choice || busy}
            >
              Replace Background
            </button>
          )}
        </div>

        <details className="advanced">
          <summary>Advanced</summary>
          <div className="chips" role="group" aria-label="Fit">
            {(["cover", "contain"] as const).map((f) => (
              <button
                key={f}
                type="button"
                className="chip"
                aria-pressed={form.fit === f}
                onClick={() => set({ fit: f })}
              >
                {f === "cover" ? "Fill frame" : "Fit inside"}
              </button>
            ))}
          </div>
          {(["background", "subject"] as const).map((what) => (
            <div key={what}>
              <label className="slider">
                <span>
                  {what === "background" ? "Background" : "Subject"} position X{" "}
                  {Math.round((what === "background" ? form.backgroundX : form.subjectX) * 100)} %
                </span>
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={(what === "background" ? form.backgroundX : form.subjectX) * 100}
                  onChange={(e) =>
                    set(
                      what === "background"
                        ? { backgroundX: Number(e.target.value) / 100 }
                        : { subjectX: Number(e.target.value) / 100 },
                    )
                  }
                />
              </label>
              <label className="slider">
                <span>
                  {what === "background" ? "Background" : "Subject"} position Y{" "}
                  {Math.round((what === "background" ? form.backgroundY : form.subjectY) * 100)} %
                </span>
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={(what === "background" ? form.backgroundY : form.subjectY) * 100}
                  onChange={(e) =>
                    set(
                      what === "background"
                        ? { backgroundY: Number(e.target.value) / 100 }
                        : { subjectY: Number(e.target.value) / 100 },
                    )
                  }
                />
              </label>
            </div>
          ))}
          <label className="slider">
            <span>Subject size {Math.round(form.subjectScale * 100)} %</span>
            <input
              type="range"
              min={10}
              max={400}
              value={form.subjectScale * 100}
              onChange={(e) => set({ subjectScale: Number(e.target.value) / 100 })}
            />
          </label>
        </details>
      </form>

      <div className="stage">
        {refining && source ? (
          <>
            <MaskEditor
              key={`refine-${source.ref}`}
              ref={editor}
              src={source.url}
              width={source.width}
              height={source.height}
              feather={form.feather}
              onFeather={(feather) => set({ feather })}
              onChange={setHasMask}
              initialMask={maskUrl}
              active={active}
            />
            <div className="row">
              <button type="button" className="btn btn-primary" onClick={() => void keepRefined()}>
                Use this mask
              </button>
              <button type="button" className="btn" onClick={() => setRefining(false)}>
                Cancel
              </button>
            </div>
          </>
        ) : source ? (
          <>
            {preview ? (
              <img className="result-image" src={preview} alt="Background preview" />
            ) : (
              <div className="background-stage">
                <img src={source.url} alt="Subject" draggable={false} />
                {showMask && maskUrl && (
                  <img className="background-overlay" src={maskUrl} alt="" aria-hidden="true" />
                )}
                {maskLoading && (
                  <p className="progress-label" aria-live="polite">
                    Finding the subject…
                  </p>
                )}
              </div>
            )}
            {choice === null && !maskLoading && (
              <p className="field-help">Choose a new background to see the preview.</p>
            )}
          </>
        ) : (
          <section className="empty" aria-label="Getting started">
            <h2>Put the subject on a new background</h2>
            <p>
              Press <strong>Background</strong> on a result or a gallery image, or upload a photo.
              P11 finds the subject; choose a photo, a description or a colour and press{" "}
              <strong>Replace Background</strong>.
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
          <section className="result" aria-label="Background result">
            <img
              className="result-image"
              src={result.url}
              alt={`New background: ${result.prompt}`}
            />
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
