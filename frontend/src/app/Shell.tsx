// The app shell: left nav, top bar, the views and the status bar. Built views stay mounted
// (hidden when inactive) so the form and gallery keep their state; later phases replace the
// placeholders.

import { useEffect, useRef, useState } from "react";
import { GalleryView } from "../features/gallery/GalleryView";
import { GenerateView } from "../features/generate/GenerateView";
import { Dialog } from "../components/Dialog";
import { useNav, VIEWS, type View } from "./nav";
import { SHORTCUTS, useShortcuts } from "./shortcuts";
import { StatusBar } from "./StatusBar";
import { useStudio } from "./studio";
import { useToasts } from "./Toasts";

type Theme = "light" | "dark";
const THEME_KEY = "p11.theme";

function initialTheme(): Theme {
  const saved = localStorage.getItem(THEME_KEY);
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function Placeholder({ view }: { view: View }) {
  const v = VIEWS.find((x) => x.id === view);
  return (
    <section className="empty placeholder" aria-label={v?.label}>
      <h2>{v?.label}</h2>
      <p>
        {v?.about} Coming in Phase {v?.phase}.
      </p>
      {view === "models" && (
        <p>
          Until then, manage models in a terminal: <code>p11 models list</code> and{" "}
          <code>p11 models install default</code>.
        </p>
      )}
    </section>
  );
}

export function Shell({ version, fake }: { version: string; fake: boolean }) {
  const { view, go } = useNav();
  const { state } = useStudio();
  const toasts = useToasts();
  const [help, setHelp] = useState(false);
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const main = useRef<HTMLElement>(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  // Tell the user once when the event stream drops (engine/service down).
  const wasConnected = useRef(false);
  useEffect(() => {
    if (state.connected === false && wasConnected.current)
      toasts.push({
        kind: "error",
        message: "Lost the connection to P11 Studio. Reconnecting…",
        hint: "If this lasts, check the service with `p11 status`.",
      });
    if (state.connected) wasConnected.current = true;
  }, [state.connected, toasts]);

  useShortcuts({ gallery: () => go("gallery"), help: () => setHelp(true) });

  const navigate = (v: View) => {
    go(v);
    main.current?.focus();
  };

  return (
    <div className="shell">
      <a className="skip" href="#main">
        Skip to content
      </a>
      <header className="topbar">
        <h1 className="brand">P11 Studio</h1>
        <span className={`session ${state.connected === false ? "offline" : "online"}`}>
          {state.connected === false ? "Reconnecting…" : "Connected"} · v{version}
          {fake ? " · fake engine" : ""}
        </span>
        <span className="grow" />
        <button
          type="button"
          className="btn btn-ghost"
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
        >
          {theme === "dark" ? "☀ Light" : "☾ Dark"}
        </button>
        <button
          type="button"
          className="btn btn-ghost"
          onClick={() => setHelp(true)}
          aria-label="Keyboard shortcuts"
        >
          ?
        </button>
      </header>
      <nav className="sidenav" aria-label="Views">
        <ul>
          {VIEWS.map((v) => (
            <li key={v.id}>
              <button
                type="button"
                className="nav-item"
                aria-current={view === v.id ? "page" : undefined}
                onClick={() => navigate(v.id)}
              >
                {v.label}
                {v.phase && <small className="nav-phase">Phase {v.phase}</small>}
              </button>
            </li>
          ))}
        </ul>
      </nav>
      <main id="main" ref={main} tabIndex={-1} className="main">
        <GenerateView active={view === "generate"} />
        <GalleryView active={view === "gallery"} />
        {view !== "generate" && view !== "gallery" && <Placeholder view={view} />}
      </main>
      <StatusBar />
      {help && (
        <Dialog title="Keyboard shortcuts" onClose={() => setHelp(false)}>
          <table className="shortcuts">
            <tbody>
              {SHORTCUTS.map((s) => (
                <tr key={s.command}>
                  <th scope="row">
                    <kbd>{s.keys}</kbd>
                  </th>
                  <td>{s.label}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="field-help">
            In an image: <kbd>+</kbd> / <kbd>−</kbd> zoom, <kbd>0</kbd> resets, arrows pan.
          </p>
        </Dialog>
      )}
    </div>
  );
}
