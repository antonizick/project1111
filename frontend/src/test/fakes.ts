// Test doubles: a routed fetch() for the Studio API and an EventSource the test drives.

import { vi } from "vitest";
import type { EventSourceLike } from "../api/events";
import type { ImageEntry, Job, ModelInfo, Presets, SystemInfo } from "../api/types";

export type Route = (init: RequestInit, url: URL) => unknown;

export function reply(status: number, body: unknown, headers: Record<string, string> = {}) {
  return {
    ok: status < 400,
    status,
    statusText: "",
    headers: new Headers(headers),
    json: async () => body,
    blob: async () => new Blob([JSON.stringify(body)]),
  };
}

export class Problem {
  constructor(
    readonly status: number,
    readonly body: { code: string; message: string; hint: string },
  ) {}
}

/** Stub fetch with routes keyed "METHOD /path" (query ignored). Unrouted calls fail the test. */
export function mockApi(routes: Record<string, Route>) {
  const calls: { method: string; path: string; body: unknown; url: URL }[] = [];
  const fetch = vi.fn(async (input: string, init: RequestInit = {}) => {
    const url = new URL(input, "http://127.0.0.1:8111");
    const method = (init.method ?? "GET").toUpperCase();
    const body = typeof init.body === "string" ? JSON.parse(init.body) : undefined;
    calls.push({ method, path: url.pathname, body, url });
    const route = routes[`${method} ${url.pathname}`];
    if (!route)
      return reply(404, {
        code: "http.404",
        message: `no route ${method} ${url.pathname}`,
        hint: "",
      });
    const out = route(init, url);
    if (out instanceof Problem) return reply(out.status, out.body);
    if (out instanceof Blob)
      return {
        ...reply(200, null, { "content-disposition": 'attachment; filename="p11-1.png"' }),
        blob: async () => out,
      };
    return reply(200, out);
  });
  vi.stubGlobal("fetch", fetch);
  return { fetch, calls };
}

export class FakeSource implements EventSourceLike {
  static last: FakeSource | null = null;
  readyState = 1;
  onopen: ((ev: Event) => unknown) | null = null;
  onerror: ((ev: Event) => unknown) | null = null;
  listeners = new Map<string, ((ev: MessageEvent) => void)[]>();
  closed = false;

  constructor(readonly url: string) {
    FakeSource.last = this;
  }
  addEventListener(type: string, l: (ev: MessageEvent) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), l]);
  }
  close() {
    this.closed = true;
    this.readyState = 2;
  }
  emit(type: string, data: unknown) {
    for (const l of this.listeners.get(type) ?? [])
      l(new MessageEvent(type, { data: JSON.stringify(data) }));
  }
}

export const createSource = (url: string) => new FakeSource(url);

export const presets: Presets = {
  aspects: [
    {
      id: "16:9-1920x1080",
      label: "Wallpaper 1920 x 1080 (16:9)",
      output: [1920, 1080],
      bucket: { sdxl: [1344, 768] },
      chain: "model",
      quality_chain: "latent",
    },
    {
      id: "16:9-2560x1440",
      label: "Wallpaper 2560 x 1440 (16:9)",
      output: [2560, 1440],
      bucket: { sdxl: [1344, 768] },
      chain: "model",
      quality_chain: "latent",
    },
    {
      id: "1:1-1024",
      label: "Square 1024",
      output: [1024, 1024],
      bucket: { sdxl: [1024, 1024] },
      chain: "model",
      quality_chain: "latent",
    },
    {
      id: "logo-1:1",
      label: "Logo (square)",
      output: [1024, 1024],
      bucket: { sdxl: [1024, 1024] },
      chain: "model",
      quality_chain: "model",
    },
    {
      id: "avatar-4:5",
      label: "Avatar (portrait)",
      output: null,
      bucket: { sdxl: [896, 1152] },
      chain: "native",
      quality_chain: "native",
    },
  ],
  styles: [
    {
      id: "photoreal",
      label: "Photoreal",
      aspect: "16:9-1920x1080",
      model: "realvisxl5-lightning",
      tags: [],
    },
    {
      id: "3d-animated-avatar",
      label: "3D animated avatar (bobblehead)",
      aspect: "avatar-4:5",
      model: "realvisxl5-lightning",
      tags: [],
    },
    {
      id: "logo-flat",
      label: "Logo (flat)",
      aspect: "logo-1:1",
      model: "realvisxl5-lightning",
      tags: [],
    },
    {
      id: "logo-3d",
      label: "Logo (3D)",
      aspect: "logo-1:1",
      model: "realvisxl5-lightning",
      tags: [],
    },
  ],
};

export const models: ModelInfo[] = [
  {
    id: "realvisxl5-lightning",
    name: "RealVisXL V5.0 Lightning (fp16)",
    kind: "checkpoint",
    base: "sdxl",
    state: "installed",
    sets: ["default"],
    enabled: true,
    usable: true,
    family: "sdxl",
    vae: "sdxl-vae-fp16-fix",
    licence: null,
    defaults: {
      sampler_name: "dpmpp_sde",
      scheduler: "karras",
      steps: 5,
      cfg: 1.5,
      clip_skip: 1,
      hires_steps: 3,
    },
  },
  {
    id: "juggernautxl9",
    name: "Juggernaut XL v9",
    kind: "checkpoint",
    base: "sdxl",
    state: "installed",
    sets: ["default"],
    enabled: true,
    usable: true,
    family: "sdxl",
    vae: null,
    licence: null,
    defaults: {
      sampler_name: "dpmpp_2m",
      scheduler: "karras",
      steps: 30,
      cfg: 4.5,
      clip_skip: 1,
      hires_steps: 15,
    },
  },
];

export const system: SystemInfo = {
  version: "0.1.0",
  fake: true,
  started_at: "2026-11-03T00:00:00+00:00",
  port: 8111,
  engine: { state: "stopped", ready: false, vram_mode: "dynamic", version: null, last_error: null },
  gpu: null,
  queue: { current: null, waiting: 0 },
};

export function job(over: Partial<Job> = {}): Job {
  return {
    id: "job1",
    state: "queued",
    name: "x",
    count: 1,
    template: null,
    created_at: "2026-11-03T10:00:00+00:00",
    updated_at: "2026-11-03T10:00:00+00:00",
    images: [],
    progress: 0,
    error: null,
    note: null,
    ...over,
  };
}

export function image(id: number, over: Partial<ImageEntry> = {}): ImageEntry {
  return {
    id,
    path: `2026-11-03/adhoc/1000${id}-${id}.png`,
    created_at: "2026-11-03T10:00:00+00:00",
    recipe_id: "r",
    template: null,
    seed: 100 + id,
    model: "realvisxl5-lightning",
    width: 1920,
    height: 1080,
    favourite: false,
    parent_id: null,
    prompt: `prompt ${id}`,
    url: `/api/images/${id}`,
    thumb: `/api/images/${id}/thumb`,
    ...over,
  };
}

/** The routes every Studio view loads. */
export function baseRoutes(): Record<string, Route> {
  return {
    "GET /api/session": () => ({ ok: true, version: "0.1.0", fake: true }),
    "GET /api/presets": () => presets,
    "GET /api/models": () => models,
    "GET /api/system": () => system,
    "GET /api/gallery": () => ({ items: [], total: 0, limit: 120, offset: 0 }),
    "GET /api/gallery/facets": () => ({ templates: [], models: [] }),
    "GET /api/trash": () => ({ count: 0, bytes: 0 }),
  };
}
