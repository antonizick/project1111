// Video view (Phase 13): face swap in short clips. Upload a clip and a face photo, pick the face
// to swap onto on the first frame, choose Fast or Good, press Swap. The job shows frame progress
// and an ETA, pauses when the laptop runs hot, can be cancelled, and resumes after a crash from
// its last finished frame. The S5 guard runs on every swapped frame (and a sampled pre-pass):
// P11 refuses nude or sexual clips and there is no switch to change that.

import { useCallback, useEffect, useId, useState } from "react";
import { client, saveDownload, type FaceBox } from "../../api/client";
import type { Job, VideoJob, VideoRequest } from "../../api/types";
import { useNav } from "../../app/nav";
import { useShortcuts } from "../../app/shortcuts";
import { useStudio } from "../../app/studio";
import { useToasts } from "../../app/Toasts";
import { useImageActions } from "../actions";
import { CONSENT_NOTICE } from "../face/recipe";
import { stageLabel } from "../generate/GenerateView";
import { formatSeconds, remainingSeconds } from "../generate/eta";

type Picked = {
  ref: string;
  url: string;
  name: string;
  seconds: number;
  warnings: string[];
};

/**
 * Rough seconds per frame until the pipeline is measured on the laptop (Phase 12: 2.4 s swap,
 * 3.9 s with GFPGAN, plus ~1.4 s of guard). docs/P11_BENCHMARKS.md → Video face-swap replaces
 * this with the measured per-frame times.
 */
const PER_FRAME_SECONDS: Record<"fast" | "good", number> = { fast: 2.5, good: 4.5 };
/** The clip's frame rate is only known after probing; the estimate assumes this. */
const ASSUMED_FPS = 30;

const SIZES: { value: string; label: string }[] = [
  { value: "", label: "Quality default" },
  { value: "2160", label: "Full size (slower)" },
  { value: "1080", label: "1080p" },
  { value: "720", label: "720p" },
];

export function VideoView({ active }: { active: boolean }) {
  const { state, dispatch } = useStudio();
  const nav = useNav();
  const toasts = useToasts();
  const id = useId();
  const actions = useImageActions();
  const [clip, setClip] = useState<Picked | null>(null);
  const [face, setFace] = useState<Picked | null>(null);
  const [frame, setFrame] = useState<string | null>(null);
  const [faces, setFaces] = useState<FaceBox[]>([]);
  const [targetFace, setTargetFace] = useState<number | null>(null);
  const [quality, setQuality] = useState<"fast" | "good">("fast");
  const [size, setSize] = useState("");
  const [trimStart, setTrimStart] = useState("");
  const [trimEnd, setTrimEnd] = useState("");
  const [smooth, setSmooth] = useState(false);
  const [keepFrames, setKeepFrames] = useState(false);
  const [confirmLimits, setConfirmLimits] = useState(false);
  const [busy, setBusy] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [detail, setDetail] = useState<VideoJob | null>(null);
  const [jobs, setJobs] = useState<VideoJob[]>([]);
  const [now, setNow] = useState(() => Date.now());

  const refresh = useCallback(() => {
    client
      .videoJobs()
      .then(setJobs)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (active) refresh();
  }, [active, refresh]);

  /** First frame + its faces, so the target face is picked on a thumbnail. */
  const lookAtClip = useCallback(async (ref: string) => {
    try {
      const still = await client.videoFrame(ref, 0);
      setFrame((old) => {
        if (old) URL.revokeObjectURL(old);
        return URL.createObjectURL(still.blob);
      });
      const found = await client.videoDetect(ref, 0);
      setFaces(found.faces);
    } catch {
      setFaces([]);
    }
    setTargetFace(null);
  }, []);

  const pickClip = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    try {
      const up = await client.upload(file, "video");
      setClip({
        ref: up.id,
        url: URL.createObjectURL(file),
        name: file.name,
        seconds: up.seconds ?? 0,
        warnings: up.warnings ?? [],
      });
      setJobId(null);
      setDetail(null);
      setConfirmLimits(false);
      await lookAtClip(up.id);
    } catch (e) {
      actions.fail(e);
    } finally {
      setBusy(false);
    }
  };

  const pickFace = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    try {
      const up = await client.upload(file, "image");
      setFace({
        ref: up.id,
        url: URL.createObjectURL(file),
        name: file.name,
        seconds: 0,
        warnings: [],
      });
    } catch (e) {
      actions.fail(e);
    } finally {
      setBusy(false);
    }
  };

  // An image opened from the gallery or a result ("Use face in Video") becomes the face photo.
  const editing = nav.editing;
  const [seen, setSeen] = useState<number | null>(null);
  if (active && editing?.view === "video" && editing.at !== seen) {
    setSeen(editing.at);
    const img = editing.image;
    setFace({
      ref: `gallery/${img.id}`,
      url: img.url,
      name: `Image ${img.id}`,
      seconds: 0,
      warnings: [],
    });
  }

  const job: Job | undefined = jobId ? state.jobs[jobId] : undefined;
  const jobState = job?.state;
  const running = jobState === "queued" || jobState === "running" || jobState === "paused";
  const progress = jobId ? state.progress[jobId] : undefined;

  const request = (): VideoRequest | null => {
    if (!clip || !face) return null;
    const end = trimEnd.trim() ? Number(trimEnd) : NaN;
    return {
      video: clip.ref,
      face: face.ref,
      quality,
      source_face_index: 0,
      target_face: targetFace,
      trim_start: Number(trimStart) || 0,
      trim_end: Number.isFinite(end) ? end : null,
      max_height: size ? Number(size) : null,
      smooth,
      keep_frames: keepFrames,
      confirm_limits: confirmLimits,
    };
  };

  const swap = async () => {
    if (busy || running) return;
    const body = request();
    if (!body) {
      toasts.push({ kind: "info", message: "Choose the clip and the face photo first." });
      return;
    }
    setBusy(true);
    try {
      const job = await client.submitVideo(body);
      dispatch({ type: "submitted", jobs: [job] });
      setJobId(job.id);
      setDetail(null);
    } catch (e) {
      actions.fail(e);
    } finally {
      setBusy(false);
    }
  };

  const cancel = () => {
    if (jobId && running) client.cancelJob(jobId).catch(actions.fail);
  };

  const resume = async (j: VideoJob) => {
    try {
      const next = await client.resumeVideo(j.id);
      dispatch({ type: "submitted", jobs: [next] });
      setJobId(next.id);
      setDetail(null);
    } catch (e) {
      actions.fail(e);
    }
  };

  useShortcuts({ escape: running ? cancel : undefined }, active);

  useEffect(() => {
    if (!jobId) return;
    if (jobState === "done") {
      client
        .videoJob(jobId)
        .then((d) => {
          setDetail(d);
          refresh();
        })
        .catch(() => undefined);
    } else if (jobState === "failed" && job?.error) {
      toasts.problem(job.error);
      refresh();
    }
    // Only react to state changes of the followed job.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, jobState]);

  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [running]);

  const elapsed =
    job?.state === "running" ? Math.max(0, (now - Date.parse(job.updated_at)) / 1000) : 0;
  const frames = progress?.total ?? detail?.frames ?? 0;
  const eta =
    job && job.state === "running" && frames > 0
      ? formatSeconds(remainingSeconds(job.progress, elapsed, frames * PER_FRAME_SECONDS[quality]))
      : null;
  const estimateMinutes = clip
    ? Math.max(1, Math.round((clip.seconds * ASSUMED_FPS * PER_FRAME_SECONDS[quality]) / 60))
    : 0;

  return (
    <div className="video-view" hidden={!active}>
      <form
        className="generate-form"
        aria-label="Video"
        onSubmit={(e) => {
          e.preventDefault();
          void swap();
        }}
      >
        <p className="field-help">
          Put a face into a short clip. The finished MP4 keeps the original sound.
        </p>
        <p className="field-help" role="note">
          {CONSENT_NOTICE} The clip is checked before and during the swap: P11 refuses nude or
          sexual clips, and there is no switch to change that.
        </p>

        <div className="field">
          <label htmlFor={`${id}-clip`}>Clip</label>
          <input
            id={`${id}-clip`}
            type="file"
            accept="video/*"
            disabled={busy}
            onChange={(e) => void pickClip(e.target.files?.[0])}
          />
          {clip && <video className="preview" src={clip.url} controls muted />}
        </div>

        {clip && clip.warnings.length > 0 && (
          <fieldset className="field">
            <legend>Over the recommended limits</legend>
            {clip.warnings.map((w) => (
              <p key={w} className="field-help">
                {w} At Fast quality this clip is roughly {estimateMinutes} minutes of work.
              </p>
            ))}
            <label className="check">
              <input
                type="checkbox"
                checked={confirmLimits}
                onChange={(e) => setConfirmLimits(e.target.checked)}
              />
              I understand, run it anyway
            </label>
          </fieldset>
        )}

        <div className="field">
          <label htmlFor={`${id}-face`}>Face photo</label>
          <input
            id={`${id}-face`}
            type="file"
            accept="image/*"
            disabled={busy}
            onChange={(e) => void pickFace(e.target.files?.[0])}
          />
          {face && <img className="preview" src={face.url} alt={face.name} />}
        </div>

        {frame && (
          <div className="field">
            <span id={`${id}-pick`}>Face to swap onto</span>
            <div className="frame-picker" role="group" aria-labelledby={`${id}-pick`}>
              <img src={frame} alt="First frame of the clip" />
              {faces.map((f, i) => (
                <button
                  key={i}
                  type="button"
                  className="face-box"
                  aria-pressed={targetFace === i}
                  aria-label={`Face ${i + 1}`}
                  title={`Face ${i + 1}`}
                  style={{
                    left: `${f.box[0] * 100}%`,
                    top: `${f.box[1] * 100}%`,
                    width: `${(f.box[2] - f.box[0]) * 100}%`,
                    height: `${(f.box[3] - f.box[1]) * 100}%`,
                  }}
                  onClick={() => setTargetFace(targetFace === i ? null : i)}
                />
              ))}
            </div>
            <p className="field-help">
              {targetFace === null
                ? "Largest face in every frame (P11 follows it)."
                : `Following face ${targetFace + 1} across the clip.`}
            </p>
          </div>
        )}

        <div className="field">
          <label htmlFor={`${id}-quality`}>Quality</label>
          <select
            id={`${id}-quality`}
            value={quality}
            onChange={(e) => setQuality(e.target.value as "fast" | "good")}
          >
            <option value="fast">Fast (no face restore, 720p)</option>
            <option value="good">Good (restored faces, full size)</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor={`${id}-size`}>Frame size</label>
          <select id={`${id}-size`} value={size} onChange={(e) => setSize(e.target.value)}>
            {SIZES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor={`${id}-start`}>Start (seconds)</label>
          <input
            id={`${id}-start`}
            type="number"
            min={0}
            step={0.5}
            value={trimStart}
            placeholder="0"
            onChange={(e) => setTrimStart(e.target.value)}
          />
          <label htmlFor={`${id}-end`}>End (seconds)</label>
          <input
            id={`${id}-end`}
            type="number"
            min={0}
            step={0.5}
            value={trimEnd}
            placeholder="whole clip"
            onChange={(e) => setTrimEnd(e.target.value)}
          />
        </div>
        <label className="check">
          <input type="checkbox" checked={smooth} onChange={(e) => setSmooth(e.target.checked)} />
          Smooth the face over time (less flicker)
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={keepFrames}
            onChange={(e) => setKeepFrames(e.target.checked)}
          />
          Keep the frames (lets you resume a cancelled run)
        </label>

        <div className="row">
          <button type="submit" className="btn btn-primary" disabled={busy}>
            Swap faces
          </button>
          {running && (
            <button type="button" className="btn btn-danger" onClick={cancel}>
              Cancel
            </button>
          )}
        </div>
      </form>

      {job && (running || jobState === "done") && (
        <section className="progress" aria-label="Progress">
          <p className="progress-label" aria-live="polite">
            {stageLabel(progress?.title, job)}
            {progress?.title === "Swapping faces" && progress.step !== undefined && progress.total
              ? ` · frame ${progress.step}/${progress.total}`
              : ""}
            {jobState === "done" && detail
              ? ` · ${detail.frames} frames (${detail.pass_through} kept as they were)`
              : ""}
          </p>
          <progress max={1} value={job.progress} aria-label="Job progress" />
          <p className="progress-sub">
            {Math.round(job.progress * 100)} % {eta ? `· ${eta}` : ""}
            {state.gpu ? ` · GPU ${Math.round(state.gpu.temp_c)} °C` : ""}
          </p>
          {job.note && <p className="note">{job.note}</p>}
        </section>
      )}

      {detail?.file && jobState === "done" && (
        <div className="result">
          <video src={detail.file} controls />
          <div className="row">
            <button
              type="button"
              className="btn"
              onClick={() =>
                client.downloadVideo(detail.record_job).then(saveDownload).catch(actions.fail)
              }
            >
              Download
            </button>
          </div>
        </div>
      )}

      {jobs.length > 0 && (
        <section className="panel" aria-label="Recent video swaps">
          <h3>Recent video swaps</h3>
          <ul className="job-list">
            {jobs.map((j) => (
              <li key={j.id}>
                <span>
                  {j.created_at.slice(0, 16).replace("T", " ")} · {j.frames || "?"} frames ·{" "}
                  {j.state}
                  {j.resumable ? " · interrupted" : ""}
                </span>
                {j.resumable && (
                  <button type="button" className="btn" onClick={() => void resume(j)}>
                    Resume
                  </button>
                )}
                {(j.state === "queued" || j.state === "running" || j.state === "paused") && (
                  <button
                    type="button"
                    className="btn btn-danger"
                    onClick={() => client.cancelJob(j.id).catch(actions.fail)}
                  >
                    Cancel
                  </button>
                )}
                {j.file && (
                  <button
                    type="button"
                    className="btn"
                    onClick={() => {
                      setJobId(j.id);
                      setDetail(j);
                    }}
                  >
                    Show result
                  </button>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
