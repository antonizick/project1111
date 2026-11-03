// Ctrl+K template palette: fuzzy search, arrows to move, Enter to run.

import { useEffect, useId, useState } from "react";
import { client } from "../../api/client";
import type { Template } from "../../api/types";
import { Dialog } from "../../components/Dialog";
import { searchTemplates } from "./slots";

export function Palette({
  onClose,
  onPick,
}: {
  onClose: () => void;
  onPick: (t: Template) => void;
}) {
  const id = useId();
  const [all, setAll] = useState<Template[] | null>(null);
  const [query, setQuery] = useState("");
  const [at, setAt] = useState(0);

  useEffect(() => {
    let live = true;
    client
      .templates()
      .then((t) => live && setAll(t))
      .catch(() => live && setAll([]));
    return () => {
      live = false;
    };
  }, []);

  const found = searchTemplates(all ?? [], query);
  const current = found[Math.min(at, found.length - 1)];

  return (
    <Dialog title="Run a template" onClose={onClose}>
      <div className="field">
        <label htmlFor={`${id}-q`}>Find a template</label>
        <input
          id={`${id}-q`}
          role="combobox"
          aria-expanded="true"
          aria-controls={`${id}-list`}
          aria-activedescendant={current ? `${id}-${current.id}` : undefined}
          value={query}
          autoComplete="off"
          onChange={(e) => {
            setQuery(e.target.value);
            setAt(0);
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setAt((i) => Math.min(i + 1, found.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setAt((i) => Math.max(i - 1, 0));
            } else if (e.key === "Enter" && current) {
              e.preventDefault();
              onPick(current);
            }
          }}
        />
      </div>
      <ul id={`${id}-list`} role="listbox" aria-label="Templates" className="palette-list">
        {found.map((t) => (
          <li
            key={t.id}
            id={`${id}-${t.id}`}
            role="option"
            aria-selected={t.id === current?.id}
            onClick={() => onPick(t)}
          >
            <strong>{t.name}</strong>
            {t.folder && <span className="muted"> · {t.folder}</span>}
          </li>
        ))}
        {all !== null && found.length === 0 && (
          <li className="muted">No template matches. Save one from any result with T.</li>
        )}
      </ul>
    </Dialog>
  );
}
