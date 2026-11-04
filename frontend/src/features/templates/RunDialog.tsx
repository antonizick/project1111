// The small slot form: one field per open input (text, or a photo by picker, gallery or drop),
// remembered per template on request ("use last face photo").

import { useId, useState } from "react";
import { client, problemOf } from "../../api/client";
import type { Slot, Template } from "../../api/types";
import { useToasts } from "../../app/Toasts";
import { Dialog } from "../../components/Dialog";
import { GalleryPicker } from "../../components/GalleryPicker";
import { isImageSlot, missingSlots, recalled, remember, slotLabel, type SlotValues } from "./slots";

function ImageInput({
  slot,
  value,
  onChange,
}: {
  slot: Slot;
  value: SlotValues[string] | undefined;
  onChange: (v: SlotValues[string]) => void;
}) {
  const id = useId();
  const toasts = useToasts();
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const take = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    try {
      const up = await client.upload(file, slot.kind === "mask" ? "mask" : "image");
      onChange({ ref: up.id, name: file.name });
    } catch (e) {
      toasts.problem(problemOf(e));
    } finally {
      setBusy(false);
    }
  };
  const chosen = typeof value === "object" ? (value.name ?? "a photo") : null;
  return (
    <div
      className={`dropzone${over ? " dropzone-over" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        void take(e.dataTransfer.files[0]);
      }}
    >
      <label htmlFor={id}>
        {slotLabel(slot)}
        {slot.required ? "" : " (optional)"}
      </label>
      <input
        id={id}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        onChange={(e) => void take(e.target.files?.[0])}
      />
      {slot.kind !== "mask" && (
        <GalleryPicker
          label={slotLabel(slot)}
          disabled={busy}
          onPick={(img) => onChange({ ref: `gallery/${img.id}`, name: `Image ${img.id}` })}
        />
      )}
      <p className="field-help" aria-live="polite">
        {busy ? "Uploading…" : chosen ? `Using ${chosen}.` : "Choose a photo or drop it here."}
      </p>
    </div>
  );
}

export function RunDialog({
  template,
  onClose,
  onRun,
}: {
  template: Template;
  onClose: () => void;
  onRun: (values: SlotValues) => void;
}) {
  const id = useId();
  const saved = recalled(template.id);
  const [values, setValues] = useState<SlotValues>(saved);
  const [keep, setKeep] = useState(Object.keys(saved).length > 0);
  const set = (name: string, v: SlotValues[string]) => setValues((cur) => ({ ...cur, [name]: v }));
  const open = missingSlots(template, values);
  const hasImages = template.slots.some(isImageSlot);

  const run = () => {
    if (open.length > 0) return;
    remember(template.id, keep ? values : null);
    onRun(values);
  };

  return (
    <Dialog title={`Run “${template.name}”`} onClose={onClose}>
      <form
        className="template-form"
        onSubmit={(e) => {
          e.preventDefault();
          run();
        }}
      >
        {template.slots.map((slot) =>
          isImageSlot(slot) ? (
            <ImageInput
              key={slot.name}
              slot={slot}
              value={values[slot.name]}
              onChange={(v) => set(slot.name, v)}
            />
          ) : (
            <div className="field" key={slot.name}>
              <label htmlFor={`${id}-${slot.name}`}>
                {slotLabel(slot)}
                {slot.required && slot.default === null ? "" : " (optional)"}
              </label>
              <textarea
                id={`${id}-${slot.name}`}
                rows={2}
                value={typeof values[slot.name] === "string" ? (values[slot.name] as string) : ""}
                placeholder={slot.default ?? ""}
                onChange={(e) => set(slot.name, e.target.value)}
              />
            </div>
          ),
        )}
        <label className="check">
          <input type="checkbox" checked={keep} onChange={(e) => setKeep(e.target.checked)} />
          Remember {hasImages ? "these inputs (the last photo)" : "these inputs"} for next time
        </label>
        {open.length > 0 && (
          <p className="field-help" role="status">
            Still needed: {open.map(slotLabel).join(", ")}.
          </p>
        )}
        <div className="row">
          <span className="grow" />
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={open.length > 0}>
            Run
          </button>
        </div>
      </form>
    </Dialog>
  );
}
