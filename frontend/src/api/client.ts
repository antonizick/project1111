// Typed calls to the Studio API. Every call goes through `api()` (session token header, ApiError
// with the server's {code, message, hint}); downloads go through `apiBlob()` the same way.

import { ApiError, api, storedToken, type Problem } from "./session";
import type {
  Facets,
  GalleryPage,
  FontInfo,
  ImageEntry,
  Job,
  ModelInfo,
  ModelLicenceRow,
  ModelOperation,
  ModelPlan,
  Presets,
  Recipe,
  RunRecord,
  SystemInfo,
  Template,
  TrashInfo,
  Upload,
  TextOverlayStep,
  VideoJob,
  VideoRequest,
} from "./types";

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});

export type PreviewRequest = {
  image: { ref: string };
  background?: { ref: string } | null;
  background_colour?: string | null;
  mask?: { ref: string } | null;
  colour_match?: boolean;
  colour_match_strength?: number;
  feather_px?: number;
  fit?: "cover" | "contain";
  background_x?: number;
  background_y?: number;
  subject_scale?: number;
  subject_x?: number;
  subject_y?: number;
  shadow?: boolean;
};

export type JobRequest = {
  recipe: Recipe;
  bindings?: Record<string, unknown>;
  count?: number;
  template?: string | null;
  parent?: number | null;
};

export type GalleryQuery = {
  q?: string;
  template?: string | null;
  model?: string | null;
  favourites?: boolean;
  limit?: number;
  offset?: number;
};

export function galleryUrl(query: GalleryQuery): string {
  const p = new URLSearchParams();
  if (query.q) p.set("q", query.q);
  if (query.template) p.set("template", query.template);
  if (query.model) p.set("model", query.model);
  if (query.favourites) p.set("favourites", "true");
  p.set("limit", String(query.limit ?? 60));
  p.set("offset", String(query.offset ?? 0));
  return `/api/gallery?${p.toString()}`;
}

export const client = {
  submitJob: (req: JobRequest) => api<Job>("/api/jobs", json(req)),
  cancelJob: (id: string) => api<Job>(`/api/jobs/${encodeURIComponent(id)}/cancel`, json({})),
  job: (id: string) => api<Job>(`/api/jobs/${encodeURIComponent(id)}`),
  recentJobs: () => api<Job[]>("/api/jobs?limit=20"),
  gallery: (query: GalleryQuery) => api<GalleryPage>(galleryUrl(query)),
  facets: () => api<Facets>("/api/gallery/facets"),
  image: (id: number) => api<ImageEntry>(`/api/images/${id}/info`),
  favourite: (id: number, favourite: boolean) =>
    api<ImageEntry>(`/api/images/${id}/favourite`, json({ favourite })),
  recipe: (id: number) => api<RunRecord>(`/api/images/${id}/recipe`),
  variations: (id: number, mode: "seed" | "prompt", count = 1) =>
    api<{ jobs: Job[] }>(`/api/images/${id}/variations`, json({ mode, count })),
  deleteImage: (id: number) =>
    api<{ deleted: number; trash: TrashInfo }>(`/api/images/${id}`, { method: "DELETE" }),
  trash: () => api<TrashInfo>("/api/trash"),
  emptyTrash: () => api<TrashInfo>("/api/trash/empty", json({})),
  presets: () => api<Presets>("/api/presets"),
  models: () => api<ModelInfo[]>("/api/models"),
  system: () => api<SystemInfo>("/api/system"),
  exportImage: (id: number, stripMetadata: boolean) =>
    apiBlob(`/api/images/${id}/export`, json({ strip_metadata: stripMetadata })),
  templates: (q = "", tag: string | null = null) => {
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    if (tag) p.set("tag", tag);
    return api<Template[]>(`/api/templates?${p.toString()}`);
  },
  createTemplate: (recipe: Recipe) => api<Template>("/api/templates", json(recipe)),
  updateTemplate: (recipe: Recipe) =>
    api<Template>(`/api/templates/${encodeURIComponent(recipe.id)}`, {
      ...json(recipe),
      method: "PUT",
    }),
  deleteTemplate: (id: string) =>
    api<null>(`/api/templates/${encodeURIComponent(id)}`, { method: "DELETE" }),
  exportTemplate: (id: string) => apiBlob(`/api/templates/${encodeURIComponent(id)}/export`),
  importTemplate: (text: string) =>
    api<Template>("/api/templates/import", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: text,
    }),
  templateFromImage: (body: {
    image_id: number;
    name: string;
    folder: string;
    tags: string[];
    seed: "fixed" | "random";
    variable_prompt: boolean;
    mask?: "auto" | "slot" | "fixed";
  }) => api<Template>("/api/templates/from-image", json(body)),
  upload: (file: Blob, kind: "image" | "mask" | "video" = "image") =>
    api<Upload>(`/api/uploads?kind=${kind}`, { method: "POST", body: file }),
  backgroundMask: (image: string, segmentationModel?: string | null) =>
    apiBlob(
      "/api/background/mask",
      json({ image: { ref: image }, segmentation_model: segmentationModel ?? null }),
    ),
  backgroundPreview: (body: PreviewRequest) => apiBlob("/api/background/preview", json(body)),
  exportImages: (ids: number[], stripMetadata: boolean) =>
    apiBlob("/api/gallery/export", json({ ids, strip_metadata: stripMetadata })),
  faceDetect: (ref: string) => api<FaceDetection>("/api/face/detect", json({ ref })),
  poseExtract: (ref: string) => api<PoseExtraction>("/api/pose/extract", json({ ref })),
  poseRender: (people: unknown[], width: number, height: number) =>
    apiBlob("/api/pose/render", json({ people, width, height })),
  // Video face-swap (Phase 13). The frame is a still from the clip (the face picker).
  videoFrame: (ref: string, time = 0) => apiBlob("/api/video/frame", json({ ref, time })),
  videoDetect: (ref: string, time = 0) =>
    api<FaceDetection>("/api/video/detect", json({ ref, time })),
  // Text overlay (Phase 14): bundled fonts and a live preview.
  fonts: () => api<{ fonts: FontInfo[] }>("/api/text/fonts"),
  textPreview: (body: {
    image?: { ref: string } | null;
    overlay: TextOverlayStep;
    width?: number;
    height?: number;
  }) => apiBlob("/api/text/preview", json(body)),
  logoExport: (id: number, body: { transparent: boolean; sizes: number[] }) =>
    apiBlob(`/api/images/${id}/logo-export`, json(body)),
  // Models page (Phase 14).
  modelPlan: (target: string) => api<ModelPlan>("/api/models/plan", json({ target })),
  modelInstall: (target: string, acceptLicences: boolean) =>
    api<ModelOperation>("/api/models/install", json({ target, accept_licences: acceptLicences })),
  modelOperations: () => api<ModelOperation[]>("/api/models/operations"),
  modelVerify: (ids: string[]) =>
    api<{ ok: boolean; models: ModelInfo[] }>("/api/models/verify", json({ ids })), // fmt: skip
  modelSetEnabled: (id: string, enabled: boolean) =>
    api<{ id: string; enabled: boolean }>(
      `/api/models/${encodeURIComponent(id)}/enabled`,
      json({ enabled }),
    ),
  modelRemove: (id: string, deleteFile: boolean) =>
    api<{ id: string; message: string }>(
      `/api/models/${encodeURIComponent(id)}?delete_file=${deleteFile}`,
      { method: "DELETE" },
    ),
  modelAdd: (body: {
    source: string;
    kind?: string | null;
    model_id?: string | null;
    allow_pickle?: boolean;
    link?: boolean;
  }) => api<ModelInfo>("/api/models/add", json(body)),
  modelLicences: () => api<{ licences: ModelLicenceRow[] }>("/api/models/licences"),
  submitVideo: (req: VideoRequest) => api<VideoJob>("/api/video/jobs", json(req)),
  videoJobs: () => api<VideoJob[]>("/api/video/jobs?limit=20"),
  videoJob: (id: string) => api<VideoJob>(`/api/video/jobs/${encodeURIComponent(id)}`),
  resumeVideo: (id: string) =>
    api<VideoJob>(`/api/video/jobs/${encodeURIComponent(id)}/resume`, json({})),
  videoFileUrl: (id: string) => `/api/video/jobs/${encodeURIComponent(id)}/file`,
  downloadVideo: (id: string) =>
    apiBlob(`/api/video/jobs/${encodeURIComponent(id)}/file?download=1`),
};

/** Faces P11 found in a picture, largest first (box normalised to the picture). */
export type FaceBox = { box: [number, number, number, number]; score: number };
export type FaceDetection = { faces: FaceBox[]; width: number; height: number };

/** Body poses P11 read out of a picture (OpenPose-18 keypoints, normalised). */
export type PoseExtraction = {
  people: ([number, number] | null)[][];
  width: number;
  height: number;
};

export type Download = { blob: Blob; filename: string };

/** Like `api()`, for responses that are files (exports). */
export async function apiBlob(path: string, init: RequestInit = {}): Promise<Download> {
  const token = storedToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("authorization", `Bearer ${token}`);
  const r = await fetch(path, { ...init, headers, credentials: "same-origin" });
  if (!r.ok) {
    let problem: Problem = { code: `http.${r.status}`, message: r.statusText, hint: "" };
    try {
      problem = (await r.json()) as Problem;
    } catch {
      // not JSON: keep the status text
    }
    throw new ApiError(r.status, problem);
  }
  const disposition = r.headers.get("content-disposition") ?? "";
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "p11-download";
  return { blob: await r.blob(), filename };
}

/** Save a downloaded file through a temporary object URL (no new window, no remote request). */
export function saveDownload({ blob, filename }: Download): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** The plain-English problem of any error (ApiError, network failure, bug). */
export function problemOf(e: unknown): Problem {
  if (e instanceof ApiError) return e.problem;
  if (e instanceof TypeError)
    return {
      code: "network",
      message: "Cannot reach the P11 service.",
      hint: "Is it running? Try `p11 status`, then `p11 start`.",
    };
  return {
    code: "internal",
    message: e instanceof Error ? e.message : "Something went wrong.",
    hint: "",
  };
}
