// Templates view: folders, tag filter, quick search, cards with the last output, one-click Run,
// Edit (opens the recipe in Generate), Duplicate, Rename, Move, Delete with undo, Export/Import.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { client, problemOf, saveDownload } from "../../api/client";
import type { Recipe, RunRecord, Template } from "../../api/types";
import { useNav } from "../../app/nav";
import { useStudio } from "../../app/studio";
import { useToasts } from "../../app/Toasts";
import { Dialog } from "../../components/Dialog";
import { newRecipeId } from "../generate/form";
import { fillDefaults } from "./slots";
import { useTemplateUi } from "./ui";

const MARK_ONLY = "mark-only";

/** A run record for "Edit": the template's recipe with slot defaults filled into the text. */
export function editRecord(t: Template): RunRecord {
  const steps = t.recipe.steps.map((s) =>
    s.type === "generate"
      ? {
          ...s,
          prompt: fillDefaults(String((s as { prompt: string }).prompt), t.slots),
          negative: fillDefaults(String((s as { negative?: string }).negative ?? ""), t.slots),
        }
      : s,
  );
  const seed = t.recipe.seed.kind === "fixed" ? t.recipe.seed.value : 0;
  const recipe: Recipe = {
    ...t.recipe,
    steps,
    slots: t.slots.filter((s) => s.kind !== "text"),
  };
  return {
    recipe,
    bindings: {},
    seed,
    template: t.slug,
    timings: {},
    model_hashes: {},
  };
}

type Edit = { template: Template; field: "name" | "folder" };

function EditDialog({
  edit,
  onClose,
  onSave,
}: {
  edit: Edit;
  onClose: () => void;
  onSave: (name: string, folder: string) => void;
}) {
  const [name, setName] = useState(edit.template.name);
  const [folder, setFolder] = useState(edit.template.folder);
  return (
    <Dialog title={edit.field === "name" ? "Rename template" : "Move template"} onClose={onClose}>
      <form
        className="template-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) onSave(name.trim(), folder.trim());
        }}
      >
        {edit.field === "name" ? (
          <div className="field">
            <label htmlFor="tpl-name">Template name</label>
            <input id="tpl-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
        ) : (
          <div className="field">
            <label htmlFor="tpl-folder">Folder (up to 3 levels, e.g. Logos/Dark)</label>
            <input id="tpl-folder" value={folder} onChange={(e) => setFolder(e.target.value)} />
          </div>
        )}
        <div className="row">
          <span className="grow" />
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary">
            Save
          </button>
        </div>
      </form>
    </Dialog>
  );
}

export function TemplatesView({ active }: { active: boolean }) {
  const { state } = useStudio();
  const toasts = useToasts();
  const nav = useNav();
  const ui = useTemplateUi();
  const [all, setAll] = useState<Template[] | null>(null);
  const [query, setQuery] = useState("");
  const [folder, setFolder] = useState<string | null>(null);
  const [tag, setTag] = useState<string | null>(null);
  const [edit, setEdit] = useState<Edit | null>(null);
  const picker = useRef<HTMLInputElement>(null);

  const reload = useCallback(
    () =>
      client
        .templates()
        .then(setAll)
        .catch((e: unknown) => toasts.problem(problemOf(e))),
    [toasts],
  );
  // Reload when shown, after a template was saved, and when a new image arrives (thumbnails).
  useEffect(() => {
    if (active) void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, ui.rev, state.galleryRev]);

  const folders = useMemo(() => {
    const counts = new Map<string, number>();
    for (const t of all ?? []) counts.set(t.folder, (counts.get(t.folder) ?? 0) + 1);
    return [...counts.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [all]);
  const tags = useMemo(() => [...new Set((all ?? []).flatMap((t) => t.tags))].sort(), [all]);

  const shown = useMemo(() => {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);
    return (all ?? []).filter((t) => {
      if (folder !== null && t.folder !== folder) return false;
      if (tag !== null && !t.tags.includes(tag)) return false;
      const gen = t.recipe.steps.find((s) => s.type === "generate") as
        { prompt?: string } | undefined;
      const hay = [t.name, t.folder, ...t.tags, gen?.prompt ?? ""].join(" ").toLowerCase();
      return words.every((w) => hay.includes(w));
    });
  }, [all, folder, tag, query]);

  const fail = (e: unknown) => toasts.problem(problemOf(e));

  const save = (t: Template, patch: Partial<Recipe>) =>
    client
      .updateTemplate({ ...t.recipe, ...patch })
      .then(reload)
      .catch(fail);

  const duplicate = (t: Template) =>
    client
      .createTemplate({
        ...t.recipe,
        id: newRecipeId(),
        name: `${t.name} copy`.slice(0, 120),
        created_at: new Date().toISOString(),
      })
      .then(reload)
      .catch(fail);

  const remove = (t: Template) =>
    client
      .deleteTemplate(t.id)
      .then(() => {
        void reload();
        toasts.push({
          kind: "info",
          message: `Deleted “${t.name}”.`,
          action: {
            label: "Undo",
            run: () =>
              client
                .createTemplate({ ...t.recipe, folder: t.folder })
                .then(reload)
                .catch(fail),
          },
        });
      })
      .catch(fail);

  const exportOne = (t: Template) => client.exportTemplate(t.id).then(saveDownload).catch(fail);

  const importFile = async (file: File | undefined) => {
    if (!file) return;
    try {
      const t = await client.importTemplate(await file.text());
      toasts.push({ kind: "info", message: `Imported “${t.name}”.` });
      await reload();
    } catch (e) {
      fail(e);
    } finally {
      if (picker.current) picker.current.value = "";
    }
  };

  return (
    <section className="templates" hidden={!active} aria-label="Templates">
      <h2 className="sr-only">Templates</h2>
      <div className="templates-toolbar">
        <div className="field grow">
          <label htmlFor="tpl-search">Search templates</label>
          <input
            id="tpl-search"
            type="search"
            value={query}
            placeholder="Name, tag or prompt"
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <button type="button" className="btn" onClick={() => picker.current?.click()}>
          Import…
        </button>
        <input
          ref={picker}
          type="file"
          accept=".json,application/json"
          className="sr-only"
          aria-label="Import a template file"
          tabIndex={-1}
          onChange={(e) => void importFile(e.target.files?.[0])}
        />
      </div>
      <div className="templates-body">
        <nav className="templates-side" aria-label="Template folders and tags">
          <ul className="folder-list">
            <li>
              <button
                type="button"
                className="nav-item"
                aria-current={folder === null ? "true" : undefined}
                onClick={() => setFolder(null)}
              >
                All templates <small>{all?.length ?? 0}</small>
              </button>
            </li>
            {folders.map(([f, n]) => (
              <li key={f}>
                <button
                  type="button"
                  className="nav-item"
                  aria-current={folder === f ? "true" : undefined}
                  onClick={() => setFolder(f)}
                >
                  {f || "No folder"} <small>{n}</small>
                </button>
              </li>
            ))}
          </ul>
          {tags.length > 0 && (
            <div className="chips" role="group" aria-label="Tags">
              {tags.map((t) => (
                <button
                  key={t}
                  type="button"
                  className="chip"
                  aria-pressed={tag === t}
                  onClick={() => setTag(tag === t ? null : t)}
                >
                  {t}
                </button>
              ))}
            </div>
          )}
        </nav>
        <ul className="template-grid" aria-label="Templates">
          {shown.map((t) => (
            <li key={t.id} className="template-card" aria-label={t.name}>
              <div className="template-thumb">
                {t.last_image ? (
                  <img src={t.last_image.thumb} alt={`Last result of ${t.name}`} />
                ) : (
                  <span className="muted">No image yet</span>
                )}
              </div>
              <h3>{t.name}</h3>
              <p className="muted">
                {[t.folder, ...t.tags.filter((x) => x !== MARK_ONLY)].filter(Boolean).join(" · ")}
              </p>
              {t.tags.includes(MARK_ONLY) && (
                <p className="field-help">
                  Makes the mark only; text on the logo arrives with the text overlay (Phase 14).
                </p>
              )}
              <div className="row">
                <button
                  type="button"
                  className="btn btn-primary"
                  aria-label={`Run ${t.name}`}
                  onClick={() => ui.run(t)}
                >
                  Run
                </button>
                {t.slots.length > 0 && (
                  <button
                    type="button"
                    className="btn"
                    aria-label={`Run ${t.name} with inputs`}
                    onClick={() => ui.run(t, { ask: true })}
                  >
                    Inputs…
                  </button>
                )}
                <button
                  type="button"
                  className="btn"
                  aria-label={`Edit ${t.name} in Generate`}
                  onClick={() => nav.openRecipe(editRecord(t))}
                >
                  Edit
                </button>
              </div>
              <div className="row">
                <button
                  type="button"
                  className="btn btn-small"
                  onClick={() => void duplicate(t)}
                  aria-label={`Duplicate ${t.name}`}
                >
                  Duplicate
                </button>
                <button
                  type="button"
                  className="btn btn-small"
                  aria-label={`Rename ${t.name}`}
                  onClick={() => setEdit({ template: t, field: "name" })}
                >
                  Rename
                </button>
                <button
                  type="button"
                  className="btn btn-small"
                  aria-label={`Move ${t.name}`}
                  onClick={() => setEdit({ template: t, field: "folder" })}
                >
                  Move
                </button>
                <button
                  type="button"
                  className="btn btn-small"
                  aria-label={`Export ${t.name}`}
                  onClick={() => void exportOne(t)}
                >
                  Export
                </button>
                <button
                  type="button"
                  className="btn btn-small btn-danger"
                  aria-label={`Delete ${t.name}`}
                  onClick={() => void remove(t)}
                >
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
        {all !== null && shown.length === 0 && (
          <div className="empty">
            <p>
              {all.length === 0
                ? "No templates yet. Save one from any result with the Save as Template button."
                : "No template matches."}
            </p>
          </div>
        )}
      </div>
      {edit && (
        <EditDialog
          edit={edit}
          onClose={() => setEdit(null)}
          onSave={(name, folderText) => {
            const e = edit;
            setEdit(null);
            void save(e.template, e.field === "name" ? { name } : { folder: folderText });
          }}
        />
      )}
    </section>
  );
}
