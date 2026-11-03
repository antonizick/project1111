// Server-sent events from GET /api/events (ADR-0022), with reconnect.
// The browser's EventSource retries by itself (sending Last-Event-ID) while the connection is
// only interrupted; when it gives up (readyState CLOSED, e.g. the service restarted with a new
// session) this opens a new one with a growing delay. The HttpOnly cookie authenticates it.

export type StudioEventType =
  "hello" | "job" | "progress" | "preview" | "image" | "gpu" | "deleted";
export const EVENT_TYPES: readonly StudioEventType[] = [
  "hello",
  "job",
  "progress",
  "preview",
  "image",
  "gpu",
  "deleted",
];

export type StudioEvent = { type: StudioEventType; data: unknown };

export type EventSourceLike = {
  readyState: number;
  onopen: ((ev: Event) => unknown) | null;
  onerror: ((ev: Event) => unknown) | null;
  addEventListener(type: string, listener: (ev: MessageEvent) => void): void;
  close(): void;
};

export type StreamOptions = {
  url?: string;
  onEvent: (ev: StudioEvent) => void;
  onStatus: (connected: boolean) => void;
  create?: (url: string) => EventSourceLike;
  /** Reconnect delays in ms; the last one repeats. */
  backoff?: number[];
};

const CLOSED = 2;

export class EventStream {
  private source: EventSourceLike | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private attempt = 0;
  private stopped = false;

  constructor(private readonly opts: StreamOptions) {}

  start(): void {
    this.stopped = false;
    this.open();
  }

  stop(): void {
    this.stopped = true;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.source?.close();
    this.source = null;
  }

  private open(): void {
    const create = this.opts.create ?? ((url: string) => new EventSource(url));
    const source = create(this.opts.url ?? "/api/events");
    this.source = source;
    source.onopen = () => {
      this.attempt = 0;
      this.opts.onStatus(true);
    };
    source.onerror = () => {
      this.opts.onStatus(false);
      if (source.readyState === CLOSED && !this.stopped) {
        source.close();
        const delays = this.opts.backoff ?? [1000, 2000, 5000, 10000];
        const delay = delays[Math.min(this.attempt, delays.length - 1)] ?? 10000;
        this.attempt += 1;
        this.timer = setTimeout(() => {
          this.timer = null;
          if (!this.stopped) this.open();
        }, delay);
      }
    };
    for (const type of EVENT_TYPES) {
      source.addEventListener(type, (ev: MessageEvent) => {
        let data: unknown;
        try {
          data = JSON.parse(String(ev.data));
        } catch {
          return; // not ours
        }
        this.opts.onEvent({ type, data });
      });
    }
  }
}
