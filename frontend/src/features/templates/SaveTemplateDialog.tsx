// Save as Template: name (prefilled from the prompt), folder, tags, seed and the "variable
// prompt" choice. Everything else is inferred on the server (templates/capture.py). Two actions
// from a result: open the dialog, press Save.

import { useEffect, useId, useState } from "react";
import { client, problemOf } from "../../api/client";
import type { ImageEntry, Template } from "../../api/types";
import { useToasts } from "../../app/Toasts";
import { Dialog } from "../../components/Dialog";
import { recipeName } from "../generate/form";

export function parseTags(text: string): string[] {
  return [
    ...new Set(
      text
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean),
    ),
  ];
}

export function SaveTemplateDialog({
  image,
  onClose,
  onSaved,
}: {
  image: ImageEntry;
  onClose: () => void;
  onSaved: (t: Template) => void;
}) {
  const toasts = useToasts();
  const id = useId();
  const [name, setName] = useState(recipeName(image.prompt));
  const [folder, setFolder] = useState("");
  const [tags, setTags] = useState("");
  const [seed, setSeed] = useState<"fixed" | "random">("random");
  const [variable, setVariable] = useState(false);
  const [folders, setFolders] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    client
      .templates()
      .then((all) => live && setFolders([...new Set(all.map((t) => t.folder).filter(Boolean))]))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  const save = async () => {
    if (busy) return;
    setBusy(true);
    try {
      onSaved(
        await client.templateFromImage({
          image_id: image.id,
          name: name.trim() || recipeName(image.prompt),
          folder: folder.trim(),
          tags: parseTags(tags),
          seed,
          variable_prompt: variable,
        }),
      );
    } catch (e) {
      toasts.problem(problemOf(e));
      setBusy(false);
    }
  };

  return (
    <Dialog title="Save as Template" onClose={onClose}>
      <form
        className="template-form"
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <div className="field">
          <label htmlFor={`${id}-name`}>Template name</label>
          <input id={`${id}-name`} value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor={`${id}-folder`}>Folder (optional)</label>
          <input
            id={`${id}-folder`}
            list={`${id}-folders`}
            value={folder}
            placeholder="e.g. Logos/Dark"
            onChange={(e) => setFolder(e.target.value)}
          />
          <datalist id={`${id}-folders`}>
            {folders.map((f) => (
              <option key={f} value={f} />
            ))}
          </datalist>
        </div>
        <div className="field">
          <label htmlFor={`${id}-tags`}>Tags (comma separated)</label>
          <input id={`${id}-tags`} value={tags} onChange={(e) => setTags(e.target.value)} />
        </div>
        <fieldset className="field">
          <legend>Each run uses</legend>
          <label className="check">
            <input
              type="radio"
              name={`${id}-seed`}
              checked={seed === "random"}
              onChange={() => setSeed("random")}
            />
            A new seed (more like this)
          </label>
          <label className="check">
            <input
              type="radio"
              name={`${id}-seed`}
              checked={seed === "fixed"}
              onChange={() => setSeed("fixed")}
            />
            This seed (exactly this)
          </label>
        </fieldset>
        <label className="check">
          <input
            type="checkbox"
            checked={variable}
            onChange={(e) => setVariable(e.target.checked)}
          />
          Ask for the prompt each time it runs
        </label>
        <p className="field-help">
          Photos you used (a face or a background) become inputs to fill in; the photos themselves
          are never stored in a template.
        </p>
        <div className="row">
          <span className="grow" />
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            Save
          </button>
        </div>
      </form>
    </Dialog>
  );
}
