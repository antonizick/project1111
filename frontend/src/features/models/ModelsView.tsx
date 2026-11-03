// Models page (Phase 14): the curated set and user models, with install progress, licence
// acknowledgements, verify, enable/disable, remove and add. Reads the Phase 06 API.

import { useCallback, useEffect, useRef, useState } from "react";
import { client, problemOf } from "../../api/client";
import type { ModelInfo, ModelLicenceRow, ModelOperation, ModelPlan } from "../../api/types";
import { Dialog } from "../../components/Dialog";
import { useStudio } from "../../app/studio";
import { useToasts } from "../../app/Toasts";

const KINDS = [
  "checkpoint",
  "lora",
  "vae",
  "upscale",
  "controlnet",
  "ipadapter",
  "clipvision",
  "segmentation",
  "faceswap",
  "facerestore",
  "facedetect",
  "classifier",
  "embedding",
];
const SETS = ["default", "full", "optional", "face", "control"];

export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes || bytes < 1) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const shown = value >= 10 || Number.isInteger(value) ? Math.round(value) : value.toFixed(1);
  return `${shown} ${units[unit]}`;
}

const STATE_LABEL: Record<string, string> = {
  installed: "Installed",
  missing: "Not installed",
  corrupt: "Damaged",
  "user-added": "Yours",
  unregistered: "On disk",
};

function Licence({ model }: { model: ModelInfo }) {
  if (!model.licence) return <span className="muted">—</span>;
  const ok = model.licence.commercial_use;
  return (
    <span className={ok ? "licence-ok" : "licence-no"} title={model.licence.flags.join(", ")}>
      {model.licence.name} · {ok ? "commercial OK" : "non-commercial"}
      {model.licence.accepted ? "" : " · not accepted"}
    </span>
  );
}

function InstallDialog({
  plan,
  onClose,
  onInstall,
}: {
  plan: ModelPlan;
  onClose: () => void;
  onInstall: () => void;
}) {
  const [accepted, setAccepted] = useState(plan.licences_to_accept.length === 0);
  return (
    <Dialog title={`Install ${plan.target}`} onClose={onClose}>
      <p>
        {plan.models.length} model(s); {plan.to_fetch.length} to download
        {plan.download_bytes ? `, ${formatBytes(plan.download_bytes)}` : ""}.
      </p>
      {plan.licences_to_accept.length > 0 && (
        <>
          <p>These licences need your acknowledgement:</p>
          <ul className="licence-list">
            {plan.licences_to_accept.map((l) => (
              <li key={l.id}>
                <strong>{l.name}</strong> — {l.licence} ·{" "}
                {l.commercial_use ? "commercial use allowed" : "NON-COMMERCIAL use only"}
                {l.url && (
                  <>
                    {" "}
                    ·{" "}
                    <a href={l.url} target="_blank" rel="noreferrer">
                      licence
                    </a>
                  </>
                )}
              </li>
            ))}
          </ul>
          <label className="check">
            <input
              type="checkbox"
              checked={accepted}
              onChange={(e) => setAccepted(e.target.checked)}
            />
            I have read and accept these licences
          </label>
        </>
      )}
      <div className="row">
        <span className="grow" />
        <button type="button" className="btn" onClick={onClose}>
          Cancel
        </button>
        <button type="button" className="btn btn-primary" disabled={!accepted} onClick={onInstall}>
          Install
        </button>
      </div>
    </Dialog>
  );
}

function RemoveDialog({
  model,
  onClose,
  onRemove,
}: {
  model: ModelInfo;
  onClose: () => void;
  onRemove: (deleteFile: boolean) => void;
}) {
  const [deleteFile, setDeleteFile] = useState(true);
  return (
    <Dialog title={`Remove ${model.name}`} onClose={onClose}>
      <p>
        {model.origin === "manifest"
          ? "This deletes the model file. You can install it again from this page."
          : "This unregisters your model from P11."}
      </p>
      <label className="check">
        <input
          type="checkbox"
          checked={deleteFile}
          onChange={(e) => setDeleteFile(e.target.checked)}
        />
        Also delete the file {model.path ?? model.filename}
      </label>
      <div className="row">
        <span className="grow" />
        <button type="button" className="btn" onClick={onClose}>
          Cancel
        </button>
        <button type="button" className="btn btn-danger" onClick={() => onRemove(deleteFile)}>
          Remove
        </button>
      </div>
    </Dialog>
  );
}

function AddDialog({ onClose, onAdded }: { onClose: () => void; onAdded: () => void }) {
  const toasts = useToasts();
  const [source, setSource] = useState("");
  const [kind, setKind] = useState("");
  const [id, setId] = useState("");
  const [allowPickle, setAllowPickle] = useState(false);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      const model = await client.modelAdd({
        source: source.trim(),
        kind: kind || null,
        model_id: id.trim() || null,
        allow_pickle: allowPickle,
      });
      toasts.push({ kind: "info", message: `Added ${model.id}.` });
      onAdded();
      onClose();
    } catch (e) {
      toasts.problem(problemOf(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog title="Add a model" onClose={onClose}>
      <div className="field">
        <label htmlFor="add-source">File path or https:// URL</label>
        <input
          id="add-source"
          value={source}
          onChange={(e) => setSource(e.target.value)}
          placeholder="/home/you/models/my-model.safetensors"
        />
        <p className="field-help">
          Safetensors and GGUF are accepted. Pickle files need the explicit opt-in below.
        </p>
      </div>
      <div className="grid-2">
        <div className="field">
          <label htmlFor="add-kind">Kind (if not detected)</label>
          <select id="add-kind" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">Detect automatically</option>
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="add-id">ID (optional)</label>
          <input id="add-id" value={id} onChange={(e) => setId(e.target.value)} />
        </div>
      </div>
      <label className="check">
        <input
          type="checkbox"
          checked={allowPickle}
          onChange={(e) => setAllowPickle(e.target.checked)}
        />
        Allow a pickle-based file (.ckpt / .pt / .bin) — pickles can run code
      </label>
      <div className="row">
        <span className="grow" />
        <button type="button" className="btn" onClick={onClose}>
          Cancel
        </button>
        <button
          type="button"
          className="btn btn-primary"
          disabled={busy || !source.trim()}
          onClick={() => void submit()}
        >
          Add
        </button>
      </div>
    </Dialog>
  );
}

export function ModelsView({ active }: { active: boolean }) {
  const { state, dispatch } = useStudio();
  const toasts = useToasts();
  const [plan, setPlan] = useState<ModelPlan | null>(null);
  const [removing, setRemoving] = useState<ModelInfo | null>(null);
  const [adding, setAdding] = useState(false);
  const [licences, setLicences] = useState<ModelLicenceRow[] | null>(null);
  const [started, setStarted] = useState<ModelOperation | null>(null);
  const reported = useRef<string | null>(null);

  const fail = useCallback((e: unknown) => toasts.problem(problemOf(e)), [toasts]);
  const refresh = useCallback(() => {
    client
      .models()
      .then((models) => dispatch({ type: "models", models }))
      .catch(() => undefined);
  }, [dispatch]);

  useEffect(() => {
    refresh();
    client
      .modelLicences()
      .then((r) => setLicences(r.licences))
      .catch(() => undefined);
  }, [refresh, state.modelsRev]);

  const models = state.models ?? [];
  const startedOp = started ? (state.modelOps[started.id] ?? started) : null;
  const running =
    (startedOp?.state === "running" ? startedOp : null) ??
    Object.values(state.modelOps).find((o) => o.state === "running") ??
    null;

  useEffect(() => {
    const failed = [startedOp, ...Object.values(state.modelOps)].find(
      (op) => op?.state === "failed" && op.error && op.id !== reported.current,
    );
    if (!failed) return;
    reported.current = failed.id;
    toasts.problem({ code: "models.install", message: failed.error!, hint: "Try again." });
  }, [startedOp, state.modelOps, toasts]);

  const install = async (target: string) => {
    setStarted(null);
    try {
      const found = await client.modelPlan(target);
      setPlan(found);
    } catch (e) {
      fail(e);
    }
  };

  const start = async () => {
    if (!plan) return;
    const target = plan.target;
    setPlan(null);
    try {
      setStarted(await client.modelInstall(target, true));
      toasts.push({ kind: "info", message: `Installing ${target}…` });
    } catch (e) {
      fail(e);
    }
  };

  const verify = async (model: ModelInfo) => {
    try {
      const result = await client.modelVerify([model.id]);
      if (result.ok) toasts.push({ kind: "info", message: `${model.name}: file verified.` });
      else
        toasts.problem({
          code: "models.corrupt",
          message: `${model.name} is damaged.`,
          hint: "Install it again from this page.",
        });
      refresh();
    } catch (e) {
      fail(e);
    }
  };

  const toggle = async (model: ModelInfo) => {
    try {
      await client.modelSetEnabled(model.id, !model.enabled);
      refresh();
    } catch (e) {
      fail(e);
    }
  };

  const remove = async (deleteFile: boolean) => {
    if (!removing) return;
    try {
      const r = await client.modelRemove(removing.id, deleteFile);
      toasts.push({ kind: "info", message: r.message });
      setRemoving(null);
      refresh();
    } catch (e) {
      fail(e);
    }
  };

  const groups = KINDS.map((kind) => ({
    kind,
    models: models.filter((m) => m.kind === kind),
  })).filter((g) => g.models.length > 0);
  const other = models.filter((m) => !KINDS.includes(m.kind));
  if (other.length) groups.push({ kind: "other", models: other });

  return (
    <div className="models" hidden={!active}>
      <section className="models-head">
        <div>
          <h2>Models</h2>
          <p className="field-help">
            {models.filter((m) => m.state === "installed" || m.state === "user-added").length}{" "}
            installed ·{" "}
            {formatBytes(
              models.reduce((sum, m) => sum + (m.state === "installed" ? (m.size ?? 0) : 0), 0),
            )}{" "}
            on disk
          </p>
        </div>
        <span className="grow" />
        <button type="button" className="btn" onClick={() => refresh()}>
          Refresh
        </button>
        <button type="button" className="btn btn-primary" onClick={() => setAdding(true)}>
          Add model
        </button>
      </section>

      <section className="models-sets" aria-label="Model sets">
        <strong>Install a set:</strong>
        {SETS.map((s) => (
          <button key={s} type="button" className="btn btn-small" onClick={() => void install(s)}>
            {s}
          </button>
        ))}
      </section>

      {running && (
        <section className="progress" aria-label="Install progress">
          <p className="progress-label" aria-live="polite">
            {running.kind === "install" ? "Installing" : "Adding"} {running.target}
            {running.label ? ` · ${running.label}` : ""}
          </p>
          <progress max={1} value={running.progress} aria-label="Download progress" />
          <p className="progress-sub">
            {`${formatBytes(running.done)}${
              running.total ? ` of ${formatBytes(running.total)}` : ""
            }`}
          </p>
        </section>
      )}

      {groups.map((g) => (
        <section key={g.kind} className="models-group">
          <h3>{g.kind}</h3>
          <table className="models-table">
            <thead>
              <tr>
                <th scope="col">Model</th>
                <th scope="col">State</th>
                <th scope="col">Size</th>
                <th scope="col">Sets</th>
                <th scope="col">Licence</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {g.models.map((m) => (
                <tr key={`${m.origin}:${m.id}`} className={m.enabled ? "" : "disabled"}>
                  <td>
                    <strong>{m.name}</strong>
                    <div className="muted">
                      {m.id} · {m.filename}
                    </div>
                    {m.detail && <div className="muted">{m.detail}</div>}
                  </td>
                  <td>{STATE_LABEL[m.state] ?? m.state}</td>
                  <td>{formatBytes(m.size)}</td>
                  <td>{m.sets.join(", ") || "—"}</td>
                  <td>
                    <Licence model={m} />
                  </td>
                  <td className="models-actions">
                    {(m.state === "missing" || m.state === "corrupt") && (
                      <button
                        type="button"
                        className="btn btn-small btn-primary"
                        onClick={() => void install(m.id)}
                      >
                        Install
                      </button>
                    )}
                    {(m.state === "installed" || m.state === "user-added") && (
                      <>
                        <button
                          type="button"
                          className="btn btn-small"
                          aria-pressed={!m.enabled}
                          onClick={() => void toggle(m)}
                        >
                          {m.enabled ? "Disable" : "Enable"}
                        </button>
                        <button
                          type="button"
                          className="btn btn-small"
                          onClick={() => void verify(m)}
                        >
                          Verify
                        </button>
                        <button
                          type="button"
                          className="btn btn-small btn-danger"
                          onClick={() => setRemoving(m)}
                        >
                          Remove
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}

      {licences && (
        <section className="models-group">
          <h3>Licences</h3>
          <ul className="licence-list">
            {licences.map((l) => (
              <li key={l.id}>
                <strong>{l.name}</strong> — {l.licence} ·{" "}
                {l.commercial_use ? "commercial use allowed" : "NON-COMMERCIAL"} ·{" "}
                {l.accepted_at
                  ? `accepted ${l.accepted_at}`
                  : l.needs_acknowledgement
                    ? "not accepted yet"
                    : "no acknowledgement needed"}
              </li>
            ))}
          </ul>
        </section>
      )}

      {plan && (
        <InstallDialog plan={plan} onClose={() => setPlan(null)} onInstall={() => void start()} />
      )}
      {removing && (
        <RemoveDialog
          model={removing}
          onClose={() => setRemoving(null)}
          onRemove={(deleteFile) => void remove(deleteFile)}
        />
      )}
      {adding && (
        <AddDialog
          onClose={() => setAdding(false)}
          onAdded={() => {
            refresh();
            client
              .modelLicences()
              .then((r) => setLicences(r.licences))
              .catch(() => undefined);
          }}
        />
      )}
    </div>
  );
}
