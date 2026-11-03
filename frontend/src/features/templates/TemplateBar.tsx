// Quick access in the Generate view: the Ctrl+K palette button and chips for the last templates
// run (one click runs one).

import { useEffect, useState } from "react";
import { client } from "../../api/client";
import type { Template } from "../../api/types";
import { useTemplateUi } from "./ui";

export function TemplateBar() {
  const ui = useTemplateUi();
  const [all, setAll] = useState<Template[]>([]);
  useEffect(() => {
    let live = true;
    client
      .templates()
      .then((t) => live && setAll(t))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [ui.rev]);
  const chips = ui.recent
    .map((id) => all.find((t) => t.id === id))
    .filter((t): t is Template => t !== undefined);
  return (
    <div className="template-bar row" role="group" aria-label="Templates">
      <button type="button" className="btn btn-small" onClick={ui.openPalette}>
        Templates <kbd>Ctrl+K</kbd>
      </button>
      {chips.map((t) => (
        <button
          key={t.id}
          type="button"
          className="chip"
          aria-label={`Run ${t.name}`}
          onClick={() => ui.run(t)}
        >
          {t.name}
        </button>
      ))}
    </div>
  );
}
