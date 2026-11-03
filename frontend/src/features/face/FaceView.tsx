// Face & Pose view (Phase 12): four one-click tools. **Swap face** puts a photo's face onto a
// picture (click the face to swap onto when there are several). **Pose** generates following a
// pose from a photo or the built-in editor. **Reference** generates in the style of a picture.
// **Restore faces** polishes the faces of a picture. The face path carries the S5 guard: P11
// refuses to put a face onto a nude or sexual image, and there is no switch to change that.

import { useId, useState } from "react";
import { client, type FaceBox } from "../../api/client";
import type { Job } from "../../api/types";
import { useNav } from "../../app/nav";
import { useStudio } from "../../app/studio";
import { useToasts } from "../../app/Toasts";
import { useImageActions } from "../actions";
import { newRecipeId } from "../generate/form";
import { ImageActions } from "../generate/ResultPanel";
import { PoseEditor, emptyPose } from "../pose-editor/PoseEditor";
import type { PoseData } from "../pose-editor/model";
import {
  CONSENT_NOTICE,
  poseRecipe,
  referenceRecipe,
  restoreRecipe,
  swapRecipe,
  type Built,
  type ControlKind,
  type ReferenceMode,
} from "./recipe";

type Tool = "swap" | "pose" | "reference" | "restore";

const TOOLS: { id: Tool; label: string; about: string }[] = [
  { id: "swap", label: "Swap face", about: "Put a photo's face onto a picture." },
  { id: "pose", label: "Apply pose", about: "Generate following a pose." },
  { id: "reference", label: "Use as reference", about: "Generate in a picture's style." },
  { id: "restore", label: "Restore faces", about: "Sharpen and polish the faces." },
];

const CONTROLS: { id: ControlKind; label: string }[] = [
  { id: "openpose", label: "Body pose" },
  { id: "depth", label: "Depth" },
  { id: "canny", label: "Lines" },
];

type Picked = { ref: string; url: string; width: number; height: number; name: string };

export function FaceView({ active }: { active: boolean }) {
  const { state, dispatch } = useStudio();
  const nav = useNav();
  const toasts = useToasts();
  const id = useId();
  const [tool, setTool] = useState<Tool>("swap");
  const [target, setTarget] = useState<Picked | null>(null);
  const [face, setFace] = useState<Picked | null>(null);
  const [reference, setReference] = useState<Picked | null>(null);
  const [posePhoto, setPosePhoto] = useState<Picked | null>(null);
  const [pose, setPose] = useState<PoseData>(() => emptyPose());
  const [poseFromEditor, setPoseFromEditor] = useState(true);
  const [control, setControl] = useState<ControlKind>("openpose");
  const [mode, setMode] = useState<ReferenceMode>("style");
  const [prompt, setPrompt] = useState("");
  const [style, setStyle] = useState("photoreal");
  const [aspect, setAspect] = useState<string | null>(null);
  const [faces, setFaces] = useState<FaceBox[]>([]);
  const [targetFace, setTargetFace] = useState(0);
  const [sourceFace, setSourceFace] = useState(0);
  const [blend, setBlend] = useState(1);
  const [restore, setRestore] = useState(true);
  const [restoreVisibility, setRestoreVisibility] = useState(1);
  const [faceIndex, setFaceIndex] = useState<number | null>(null);
  const [strength, setStrength] = useState(0.8);
  const [weight, setWeight] = useState(0.7);
  const [busy, setBusy] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const actions = useImageActions((jobs: Job[]) => setJobId(jobs[0]?.id ?? null));

  /** Find the faces in the picture being edited, so the user can click the right one. */
  const findFaces = async (picked: Picked) => {
    try {
      const found = await client.faceDetect(picked.ref);
      setFaces(found.faces);
      setTargetFace(0);
    } catch {
      setFaces([]);
    }
  };

  const pickTarget = (picked: Picked) => {
    setTarget(picked);
    setJobId(null);
    void findFaces(picked);
  };

  const upload = async (file: File | undefined, into: (p: Picked) => void) => {
    if (!file) return;
    setBusy(true);
    try {
      const up = await client.upload(file, "image");
      into({
        ref: up.id,
        url: URL.createObjectURL(file),
        width: up.width,
        height: up.height,
        name: file.name,
      });
    } catch (e) {
      actions.fail(e);
    } finally {
      setBusy(false);
    }
  };

  // Opened from a result panel or the gallery.
  const editing = nav.editing;
  const [seen, setSeen] = useState<number | null>(null);
  if (active && editing?.view === "face" && editing.at !== seen) {
    setSeen(editing.at);
    const img = editing.image;
    pickTarget({
      ref: `gallery/${img.id}`,
      url: img.url,
      width: img.width ?? 1024,
      height: img.height ?? 1024,
      name: `Image ${img.id}`,
    });
    setPrompt(img.prompt ?? "");
  }

  const build = async (): Promise<Built | null> => {
    const at = { id: newRecipeId(), now: new Date() };
    if (tool === "swap") {
      if (!target || !face) return null;
      return swapRecipe(
        {
          targetRef: target.ref,
          faceRef: face.ref,
          sourceFaceIndex: sourceFace,
          targetFaceIndex: targetFace,
          blend,
          restore,
          restoreVisibility,
        },
        at,
      );
    }
    if (tool === "restore") {
      if (!target) return null;
      return restoreRecipe({ targetRef: target.ref, faceIndex, visibility: restoreVisibility }, at);
    }
    if (tool === "pose") {
      if (!prompt.trim()) return null;
      let poseRef: string;
      if (poseFromEditor) {
        const { blob } = await client.poseRender(pose.people, pose.width, pose.height);
        poseRef = (await client.upload(blob, "image")).id;
      } else if (posePhoto) {
        poseRef = posePhoto.ref;
      } else {
        return null;
      }
      return poseRecipe(
        {
          prompt,
          style,
          aspect,
          poseRef,
          preprocess: !poseFromEditor,
          control,
          strength,
          start: 0,
          end: 1,
        },
        at,
      );
    }
    if (!prompt.trim() || !reference) return null;
    return referenceRecipe(
      { prompt, style, aspect, referenceRef: reference.ref, mode, weight, start: 0, end: 1 },
      at,
    );
  };

  const apply = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const built = await build();
      if (!built) {
        toasts.push({ kind: "info", message: "Fill in the picture and the prompt first." });
        return;
      }
      const job = await client.submitJob({
        recipe: built.recipe,
        bindings: built.bindings,
        parent: target && tool !== "pose" && tool !== "reference" ? targetUrlId() : null,
      });
      dispatch({ type: "submitted", jobs: [job] });
      setJobId(job.id);
    } catch (e) {
      actions.fail(e);
    } finally {
      setBusy(false);
    }
  };

  const targetUrlId = (): number | null => {
    const m = /^gallery\/(\d+)$/.exec(target?.ref ?? "");
    return m ? Number(m[1]) : null;
  };

  const job = jobId ? state.jobs[jobId] : undefined;
  const result =
    job?.state === "done" && job.images[0] !== undefined ? state.images[job.images[0]] : undefined;

  return (
    <section className="face-view" aria-label="Face &amp; Pose">
      <nav className="tool-tabs" aria-label="Tools">
        {TOOLS.map((t) => (
          <button
            key={t.id}
            type="button"
            aria-pressed={tool === t.id}
            className={tool === t.id ? "chip active" : "chip"}
            title={t.about}
            onClick={() => setTool(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>
      <p className="hint">{TOOLS.find((t) => t.id === tool)?.about}</p>

      {(tool === "swap" || tool === "restore") && (
        <div className="form-row">
          <label htmlFor={`${id}-target`}>Picture</label>
          <input
            id={`${id}-target`}
            type="file"
            accept="image/*"
            onChange={(e) => upload(e.target.files?.[0], pickTarget)}
          />
          {target && <img className="thumb" src={target.url} alt={target.name} />}
        </div>
      )}

      {tool === "swap" && (
        <div className="panel">
          <p className="notice" role="note">
            {CONSENT_NOTICE}
          </p>
          <div className="form-row">
            <label htmlFor={`${id}-face`}>Face photo</label>
            <input
              id={`${id}-face`}
              type="file"
              accept="image/*"
              onChange={(e) => upload(e.target.files?.[0], setFace)}
            />
            {face && <img className="thumb" src={face.url} alt={face.name} />}
          </div>
          {target && faces.length > 1 && (
            <div className="form-row">
              <label htmlFor={`${id}-tf`}>Face to swap onto</label>
              <select
                id={`${id}-tf`}
                value={targetFace}
                onChange={(e) => setTargetFace(Number(e.target.value))}
              >
                {faces.map((_, i) => (
                  <option key={i} value={i}>
                    Face {i + 1} (largest first)
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="form-row">
            <label htmlFor={`${id}-sf`}>Face in the photo</label>
            <select
              id={`${id}-sf`}
              value={sourceFace}
              onChange={(e) => setSourceFace(Number(e.target.value))}
            >
              <option value={0}>Largest face</option>
              <option value={1}>Second largest</option>
              <option value={2}>Third largest</option>
            </select>
          </div>
          <div className="form-row">
            <label htmlFor={`${id}-blend`}>Blend: {Math.round(blend * 100)} %</label>
            <input
              id={`${id}-blend`}
              type="range"
              min={0.2}
              max={1}
              step={0.05}
              value={blend}
              onChange={(e) => setBlend(Number(e.target.value))}
            />
          </div>
          <div className="form-row">
            <label htmlFor={`${id}-restore`}>
              <input
                id={`${id}-restore`}
                type="checkbox"
                checked={restore}
                onChange={(e) => setRestore(e.target.checked)}
              />
              Restore the face afterwards
            </label>
          </div>
          {restore && (
            <div className="form-row">
              <label htmlFor={`${id}-rv`}>
                Restore strength: {Math.round(restoreVisibility * 100)} %
              </label>
              <input
                id={`${id}-rv`}
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={restoreVisibility}
                onChange={(e) => setRestoreVisibility(Number(e.target.value))}
              />
            </div>
          )}
        </div>
      )}

      {tool === "restore" && target && (
        <div className="panel">
          <div className="form-row">
            <label htmlFor={`${id}-which`}>Which faces</label>
            <select
              id={`${id}-which`}
              value={faceIndex === null ? "all" : String(faceIndex)}
              onChange={(e) =>
                setFaceIndex(e.target.value === "all" ? null : Number(e.target.value))
              }
            >
              <option value="all">Every face</option>
              {[0, 1, 2, 3].map((i) => (
                <option key={i} value={i}>
                  Face {i + 1} (largest first)
                </option>
              ))}
            </select>
          </div>
          <div className="form-row">
            <label htmlFor={`${id}-vis`}>Strength: {Math.round(restoreVisibility * 100)} %</label>
            <input
              id={`${id}-vis`}
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={restoreVisibility}
              onChange={(e) => setRestoreVisibility(Number(e.target.value))}
            />
          </div>
        </div>
      )}

      {(tool === "pose" || tool === "reference") && (
        <div className="panel">
          <div className="form-row">
            <label htmlFor={`${id}-prompt`}>Prompt</label>
            <input
              id={`${id}-prompt`}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="what to generate"
            />
          </div>
          <div className="form-row">
            <label htmlFor={`${id}-style`}>Style</label>
            <select id={`${id}-style`} value={style} onChange={(e) => setStyle(e.target.value)}>
              {(state.presets?.styles ?? []).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>
          <div className="form-row">
            <label htmlFor={`${id}-aspect`}>Size</label>
            <select
              id={`${id}-aspect`}
              value={aspect ?? ""}
              onChange={(e) => setAspect(e.target.value || null)}
            >
              <option value="">Style default</option>
              {(state.presets?.aspects ?? []).map((a) => (
                <option key={a.id} value={a.id}>
                  {a.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      )}

      {tool === "pose" && (
        <div className="panel">
          <div className="form-row">
            <label htmlFor={`${id}-src`}>Pose from</label>
            <select
              id={`${id}-src`}
              value={poseFromEditor ? "editor" : "photo"}
              onChange={(e) => setPoseFromEditor(e.target.value === "editor")}
            >
              <option value="editor">The editor</option>
              <option value="photo">A photo</option>
            </select>
            {!poseFromEditor && (
              <input
                type="file"
                accept="image/*"
                aria-label="Pose photo"
                onChange={(e) => upload(e.target.files?.[0], setPosePhoto)}
              />
            )}
          </div>
          {poseFromEditor && <PoseEditor data={pose} onChange={setPose} />}
          <div className="form-row">
            <label htmlFor={`${id}-control`}>Control</label>
            <select
              id={`${id}-control`}
              value={control}
              onChange={(e) => setControl(e.target.value as ControlKind)}
            >
              {CONTROLS.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>
          <div className="form-row">
            <label htmlFor={`${id}-strength`}>Strength: {Math.round(strength * 100)} %</label>
            <input
              id={`${id}-strength`}
              type="range"
              min={0}
              max={1.5}
              step={0.05}
              value={strength}
              onChange={(e) => setStrength(Number(e.target.value))}
            />
          </div>
        </div>
      )}

      {tool === "reference" && (
        <div className="panel">
          <div className="form-row">
            <label htmlFor={`${id}-ref`}>Reference image</label>
            <input
              id={`${id}-ref`}
              type="file"
              accept="image/*"
              onChange={(e) => upload(e.target.files?.[0], setReference)}
            />
            {reference && <img className="thumb" src={reference.url} alt={reference.name} />}
          </div>
          <div className="form-row">
            <label htmlFor={`${id}-mode`}>What to keep</label>
            <select
              id={`${id}-mode`}
              value={mode}
              onChange={(e) => setMode(e.target.value as ReferenceMode)}
            >
              <option value="style">Style and colours</option>
              <option value="character">The person or character</option>
            </select>
          </div>
          <div className="form-row">
            <label htmlFor={`${id}-weight`}>Strength: {Math.round(weight * 100)} %</label>
            <input
              id={`${id}-weight`}
              type="range"
              min={0}
              max={1.5}
              step={0.05}
              value={weight}
              onChange={(e) => setWeight(Number(e.target.value))}
            />
          </div>
        </div>
      )}

      <div className="form-row actions">
        <button type="button" className="primary" onClick={apply} disabled={busy}>
          {tool === "swap" ? "Swap face" : tool === "restore" ? "Restore faces" : "Apply"}
        </button>
      </div>

      {result && (
        <div className="result">
          <img src={result.url} alt="Result" />
          <ImageActions image={result} actions={actions} />
        </div>
      )}
    </section>
  );
}
