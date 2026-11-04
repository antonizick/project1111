// Advanced settings (R18): model, LoRAs, negative prompt, sampler, scheduler, steps, CFG, seed
// lock and upscale chain. Empty fields show the model's manifest default as their placeholder.

import type { Chain, ModelInfo, Presets } from "../../api/types";
import {
  clampDenoise,
  defaultsFor,
  DENOISE_MAX,
  DENOISE_MIN,
  effectiveAspect,
  effectiveModel,
  MAX_SEED,
  PHOTO_PRESETS,
  resetAdvanced,
  withModel,
  type FormState,
} from "./form";

export const SAMPLERS = [
  "euler",
  "euler_ancestral",
  "dpmpp_2m",
  "dpmpp_2m_sde",
  "dpmpp_sde",
  "dpmpp_3m_sde",
  "ddim",
  "uni_pc",
];
export const SCHEDULERS = ["normal", "karras", "exponential", "sgm_uniform", "simple", "beta"];
const CHAINS: { id: Chain; label: string }[] = [
  { id: "native", label: "None (native size)" },
  { id: "model", label: "Model upscaler (fast)" },
  { id: "latent", label: "Latent refine (detail)" },
  { id: "both", label: "Both" },
];

function withOption(list: string[], value: string | undefined): string[] {
  return value && !list.includes(value) ? [value, ...list] : list;
}

function numberOrNull(v: string): number | null {
  if (v.trim() === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

export function AdvancedDrawer({
  form,
  setForm,
  presets,
  models,
  lastSeed,
}: {
  form: FormState;
  setForm: (f: FormState) => void;
  presets: Presets | null;
  models: ModelInfo[] | null;
  lastSeed: number | null;
}) {
  const checkpoints = (models ?? []).filter((m) => m.kind === "checkpoint" && m.enabled);
  const loras = (models ?? []).filter((m) => m.kind === "lora" && m.usable);
  const model = effectiveModel(form, presets);
  const defaults = defaultsFor(model, models);
  const aspect = presets?.aspects.find((a) => a.id === effectiveAspect(form, presets));
  const set = (patch: Partial<FormState>) => setForm({ ...form, ...patch });

  const chip = PHOTO_PRESETS.find((p) => p.id === form.strength);

  return (
    <section className="advanced" aria-label="Advanced settings">
      {form.photo && (
        <div className="field">
          <label htmlFor="adv-denoise">
            Photo strength: {(form.denoise ?? chip?.denoise ?? 0.55).toFixed(2)}
          </label>
          <input
            id="adv-denoise"
            type="range"
            min={DENOISE_MIN}
            max={DENOISE_MAX}
            step={0.05}
            value={form.denoise ?? chip?.denoise ?? 0.55}
            onChange={(e) => set({ denoise: clampDenoise(Number(e.target.value)) })}
          />
          <p className="field-help">
            {form.denoise === null
              ? `Following the ${chip?.label ?? "Change"} chip. Lower keeps more of the photo.`
              : "Custom strength. Pick a Strength chip to go back to a tuned value."}
          </p>
        </div>
      )}
      <div className="field">
        <label htmlFor="adv-model">Model</label>
        <select
          id="adv-model"
          value={form.model ?? ""}
          onChange={(e) => setForm(withModel(form, e.target.value || null))}
        >
          <option value="">Style default{model ? ` (${model})` : ""}</option>
          {checkpoints.map((m) => (
            <option key={m.id} value={m.id} disabled={!m.usable}>
              {m.name} · {(m.family ?? m.base ?? "?").toUpperCase()}
              {m.sets.includes("default") ? " · default" : ""}
              {m.usable ? "" : " · not installed"}
            </option>
          ))}
        </select>
        {defaults && (
          <p className="field-help">
            Model defaults: {defaults.sampler_name} / {defaults.scheduler}, {defaults.steps} steps,
            CFG {defaults.cfg}.
          </p>
        )}
      </div>

      <div className="field">
        <label htmlFor="adv-negative">Negative prompt</label>
        <textarea
          id="adv-negative"
          rows={2}
          value={form.negative}
          placeholder="Things to avoid (added to the style's own list)"
          onChange={(e) => set({ negative: e.target.value })}
        />
      </div>

      <fieldset className="field">
        <legend>LoRAs</legend>
        {loras.length === 0 && <p className="field-help">No LoRAs installed.</p>}
        {form.loras.map((l, i) => (
          <div key={`${l.id}-${i}`} className="row">
            <span className="grow">{l.id}</span>
            <label className="sr-only" htmlFor={`lora-w-${i}`}>
              Weight of {l.id}
            </label>
            <input
              id={`lora-w-${i}`}
              type="number"
              step={0.05}
              min={-5}
              max={5}
              value={l.weight}
              onChange={(e) =>
                set({
                  loras: form.loras.map((x, j) =>
                    j === i ? { ...x, weight: numberOrNull(e.target.value) ?? 0 } : x,
                  ),
                })
              }
            />
            <button
              type="button"
              className="btn btn-small"
              onClick={() => set({ loras: form.loras.filter((_, j) => j !== i) })}
            >
              Remove
            </button>
          </div>
        ))}
        {loras.length > 0 && form.loras.length < 8 && (
          <select
            aria-label="Add a LoRA"
            value=""
            onChange={(e) =>
              e.target.value && set({ loras: [...form.loras, { id: e.target.value, weight: 0.8 }] })
            }
          >
            <option value="">Add a LoRA…</option>
            {loras.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
        )}
      </fieldset>

      <div className="grid-2">
        <div className="field">
          <label htmlFor="adv-sampler">Sampler</label>
          <select
            id="adv-sampler"
            value={form.sampler ?? ""}
            onChange={(e) => set({ sampler: e.target.value || null })}
          >
            <option value="">Default ({defaults?.sampler_name ?? "model"})</option>
            {withOption(SAMPLERS, defaults?.sampler_name).map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="adv-scheduler">Scheduler</label>
          <select
            id="adv-scheduler"
            value={form.scheduler ?? ""}
            onChange={(e) => set({ scheduler: e.target.value || null })}
          >
            <option value="">Default ({defaults?.scheduler ?? "model"})</option>
            {withOption(SCHEDULERS, defaults?.scheduler).map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="adv-steps">Steps</label>
          <input
            id="adv-steps"
            type="number"
            min={1}
            max={200}
            placeholder={defaults ? String(defaults.steps) : ""}
            value={form.steps ?? ""}
            onChange={(e) => set({ steps: numberOrNull(e.target.value) })}
          />
        </div>
        <div className="field">
          <label htmlFor="adv-cfg">CFG</label>
          <input
            id="adv-cfg"
            type="number"
            min={0}
            max={30}
            step={0.5}
            placeholder={defaults ? String(defaults.cfg) : ""}
            value={form.cfg ?? ""}
            onChange={(e) => set({ cfg: numberOrNull(e.target.value) })}
          />
        </div>
      </div>

      <div className="field">
        <label htmlFor="adv-seed">Seed</label>
        <div className="row">
          <input
            id="adv-seed"
            type="number"
            min={0}
            max={MAX_SEED}
            className="grow"
            placeholder="Random"
            disabled={!form.seedLocked}
            value={form.seedLocked ? (form.seed ?? "") : ""}
            onChange={(e) => set({ seed: numberOrNull(e.target.value) })}
          />
          <label className="check">
            <input
              type="checkbox"
              checked={form.seedLocked}
              onChange={(e) =>
                set({
                  seedLocked: e.target.checked,
                  seed:
                    e.target.checked && form.seed === null
                      ? (lastSeed ?? Math.floor(Math.random() * 2 ** 32))
                      : form.seed,
                })
              }
            />
            Lock seed
          </label>
        </div>
      </div>

      <div className="field">
        <label htmlFor="adv-chain">Upscale</label>
        <select
          id="adv-chain"
          value={form.chain ?? ""}
          onChange={(e) => set({ chain: (e.target.value || null) as Chain | null })}
        >
          <option value="">
            Preset default
            {aspect ? ` (${form.quality ? aspect.quality_chain : aspect.chain})` : ""}
          </option>
          {CHAINS.map((c) => (
            <option key={c.id} value={c.id}>
              {c.label}
            </option>
          ))}
        </select>
      </div>

      <button type="button" className="btn btn-small" onClick={() => setForm(resetAdvanced(form))}>
        Reset to model defaults
      </button>
    </section>
  );
}
