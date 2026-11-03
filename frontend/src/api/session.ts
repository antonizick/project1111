// Session bootstrap (ADR-0022). `p11 open` opens `/#launch=<one-time code>`; the page trades the
// code for the session token at POST /api/session, keeps the token in sessionStorage (this tab
// only) and removes the fragment from the address bar. Every API call sends the token in a
// header; the HttpOnly cookie set by the same call lets <img> and EventSource load /api URLs.

const STORAGE_KEY = "p11.token";

export type Problem = { code: string; message: string; hint: string };

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly problem: Problem,
  ) {
    super(problem.message);
  }
}

export function storedToken(): string | null {
  return sessionStorage.getItem(STORAGE_KEY);
}

export function launchCode(hash: string): string | null {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  return params.get("launch");
}

/** Redeem a launch code in the URL fragment if there is one; returns the token or null. */
export async function bootstrapSession(): Promise<string | null> {
  const code = launchCode(window.location.hash);
  if (code) {
    // Drop the code from the address bar and history before anything else can read it.
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
    const r = await fetch("/api/session", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ code }),
      credentials: "same-origin",
    });
    if (!r.ok) throw new ApiError(r.status, (await r.json()) as Problem);
    const { token } = (await r.json()) as { token: string };
    sessionStorage.setItem(STORAGE_KEY, token);
    return token;
  }
  return storedToken();
}

/** fetch() for /api with the session token; throws ApiError with the server's problem. */
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
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
  return (await r.json()) as T;
}
