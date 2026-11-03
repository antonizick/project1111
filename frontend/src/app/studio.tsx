// The Studio's client-side state: jobs, progress, previews, images, GPU and system status.
// Fed by the SSE stream (api/events.ts) and a slow /api/system poll; views read it with
// useStudio(). The reducer is pure so it is tested without a browser.

import { createContext, useContext, useEffect, useMemo, useReducer, type ReactNode } from "react";
import { client } from "../api/client";
import { EventStream, type EventSourceLike, type StudioEvent } from "../api/events";
import type {
  GpuSample,
  ImageEntry,
  Job,
  ModelInfo,
  Presets,
  ProgressEvent,
  SystemInfo,
} from "../api/types";

export type StudioState = {
  /** null while the first connection is being made. */
  connected: boolean | null;
  jobs: Record<string, Job>;
  progress: Record<string, ProgressEvent>;
  previews: Record<string, string>;
  images: Record<number, ImageEntry>;
  /** Bumped whenever the gallery changed (new, updated or deleted image). */
  galleryRev: number;
  gpu: GpuSample | null;
  system: SystemInfo | null;
  presets: Presets | null;
  models: ModelInfo[] | null;
  /** Model of the latest job submitted from this tab (status bar). */
  currentModel: string | null;
};

export const initialState: StudioState = {
  connected: null,
  jobs: {},
  progress: {},
  previews: {},
  images: {},
  galleryRev: 0,
  gpu: null,
  system: null,
  presets: null,
  models: null,
  currentModel: null,
};

export type Action =
  | { type: "event"; event: StudioEvent }
  | { type: "status"; connected: boolean }
  | { type: "system"; system: SystemInfo }
  | { type: "presets"; presets: Presets }
  | { type: "models"; models: ModelInfo[] }
  | { type: "submitted"; jobs: Job[]; model?: string | null }
  | { type: "image"; image: ImageEntry }
  /** Images loaded by a view (gallery page): cached without counting as a gallery change. */
  | { type: "cache"; images: ImageEntry[] }
  | { type: "deleted"; id: number };

function putJob(state: StudioState, job: Job): StudioState {
  return { ...state, jobs: { ...state.jobs, [job.id]: { ...state.jobs[job.id], ...job } } };
}

function withImage(state: StudioState, image: ImageEntry): StudioState {
  return {
    ...state,
    images: { ...state.images, [image.id]: image },
    galleryRev: state.galleryRev + 1,
  };
}

function withoutImage(state: StudioState, id: number): StudioState {
  const images = { ...state.images };
  delete images[id];
  return { ...state, images, galleryRev: state.galleryRev + 1 };
}

export function reduce(state: StudioState, action: Action): StudioState {
  switch (action.type) {
    case "status":
      return { ...state, connected: action.connected };
    case "system":
      return { ...state, system: action.system, gpu: action.system.gpu ?? state.gpu };
    case "presets":
      return { ...state, presets: action.presets };
    case "models":
      return { ...state, models: action.models };
    case "submitted": {
      let next = state;
      for (const job of action.jobs) next = putJob(next, job);
      return action.model !== undefined ? { ...next, currentModel: action.model } : next;
    }
    case "image":
      return withImage(state, action.image);
    case "cache": {
      const images = { ...state.images };
      for (const i of action.images) images[i.id] = i;
      return { ...state, images };
    }
    case "deleted":
      return withoutImage(state, action.id);
    case "event":
      return reduceEvent(state, action.event);
  }
}

function reduceEvent(state: StudioState, { type, data }: StudioEvent): StudioState {
  switch (type) {
    case "hello": {
      const jobs = (data as { jobs?: Job[] }).jobs ?? [];
      let next: StudioState = { ...state, connected: true };
      for (const job of jobs) next = putJob(next, job);
      return next;
    }
    case "job": {
      const job = data as Job;
      let next = putJob(state, job);
      if (job.state === "done" || job.state === "failed" || job.state === "cancelled") {
        const progress = { ...next.progress };
        const previews = { ...next.previews };
        delete progress[job.id];
        delete previews[job.id];
        next = { ...next, progress, previews };
      }
      return next;
    }
    case "progress": {
      const ev = data as ProgressEvent;
      const prev = state.progress[ev.job];
      // `executing` events carry no step; keep the last step count for the same graph.
      const merged =
        ev.step === undefined && prev && prev.graph === ev.graph && prev.run === ev.run
          ? { ...prev, ...ev, step: prev.step, total: prev.total }
          : ev;
      const job = state.jobs[ev.job];
      const jobs = job
        ? { ...state.jobs, [ev.job]: { ...job, progress: ev.progress } }
        : state.jobs;
      return { ...state, jobs, progress: { ...state.progress, [ev.job]: merged } };
    }
    case "preview": {
      const ev = data as { job: string; mime: string; data: string };
      return {
        ...state,
        previews: { ...state.previews, [ev.job]: `data:${ev.mime};base64,${ev.data}` },
      };
    }
    case "image": {
      const image = (data as { image: ImageEntry | null }).image;
      return image ? withImage(state, image) : state;
    }
    case "deleted":
      return withoutImage(state, (data as { image: number }).image);
    case "gpu":
      return { ...state, gpu: data as GpuSample };
  }
}

type Ctx = {
  state: StudioState;
  dispatch: (a: Action) => void;
};

const StudioContext = createContext<Ctx | null>(null);

export const SYSTEM_POLL_MS = 5000;

export function StudioProvider({
  children,
  createSource,
}: {
  children: ReactNode;
  createSource?: (url: string) => EventSourceLike;
}) {
  const [state, dispatch] = useReducer(reduce, initialState);

  useEffect(() => {
    const stream = new EventStream({
      onEvent: (event) => dispatch({ type: "event", event }),
      onStatus: (connected) => dispatch({ type: "status", connected }),
      create: createSource,
    });
    stream.start();
    return () => stream.stop();
  }, [createSource]);

  useEffect(() => {
    let cancelled = false;
    client
      .presets()
      .then((presets) => !cancelled && dispatch({ type: "presets", presets }))
      .catch(() => undefined);
    client
      .models()
      .then((models) => !cancelled && dispatch({ type: "models", models }))
      .catch(() => undefined);
    const poll = () =>
      client
        .system()
        .then((system) => !cancelled && dispatch({ type: "system", system }))
        .catch(() => undefined);
    void poll();
    const timer = setInterval(poll, SYSTEM_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  const value = useMemo(() => ({ state, dispatch }), [state]);
  return <StudioContext.Provider value={value}>{children}</StudioContext.Provider>;
}

export function useStudio(): Ctx {
  const ctx = useContext(StudioContext);
  if (!ctx) throw new Error("useStudio outside StudioProvider");
  return ctx;
}
