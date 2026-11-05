// The app shell: left nav, top bar, the views and the status bar. Built views stay mounted
// (hidden when inactive) so the form and gallery keep their state until Reset remounts them;
// later phases replace the placeholders.

import { Fragment, useEffect, useRef, useState } from "react";
import { GalleryView } from "../features/gallery/GalleryView";
import { GenerateView } from "../features/generate/GenerateView";
import { BackgroundView } from "../features/background/BackgroundView";
import { FaceView } from "../features/face/FaceView";
import { InpaintView } from "../features/inpaint/InpaintView";
import { ModelsView } from "../features/models/ModelsView";
import { TemplatesView } from "../features/templates/TemplatesView";
import { VideoView } from "../features/video/VideoView";
import { Dialog } from "../components/Dialog";
import { useNav, VIEWS, type View } from "./nav";
import { ResetDialog } from "./ResetDialog";
import { SHORTCUTS, useShortcuts } from "./shortcuts";
import { StatusBar } from "./StatusBar";
import { useStudio } from "./studio";
import { useToasts } from "./Toasts";

type Theme = "light" | "dark";
const BUILT: ReadonlySet<View> = new Set([
  "generate",
  "gallery",
  "templates",
  "inpaint",
  "background",
  "face",
  "video",
  "models",
]);
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
  const { view, go, resetKey, reset } = useNav();
  const { state, dispatch } = useStudio();
  const toasts = useToasts();
  const [help, setHelp] = useState(false);
  const [resetting, setResetting] = useState(false);
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

  const resetStudio = () => {
    setResetting(false);
    dispatch({ type: "reset" });
    reset();
    toasts.clear();
    toasts.push({ kind: "info", message: "Studio reset. Nothing on disk changed." });
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
        <button
          type="button"
          className="btn btn-ghost"
          onClick={() => setResetting(true)}
          aria-label="Reset Studio: clear all tabs"
        >
          Reset
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
        <Fragment key={resetKey}>
          <GenerateView active={view === "generate"} />
          <GalleryView active={view === "gallery"} />
          <TemplatesView active={view === "templates"} />
          <InpaintView active={view === "inpaint"} />
          <BackgroundView active={view === "background"} />
          <FaceView active={view === "face"} />
          <VideoView active={view === "video"} />
          <ModelsView active={view === "models"} />
        </Fragment>
        {!BUILT.has(view) && <Placeholder view={view} />}
      </main>
      <StatusBar />
      {resetting && <ResetDialog onClose={() => setResetting(false)} onReset={resetStudio} />}
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
