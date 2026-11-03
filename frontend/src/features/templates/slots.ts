// Pure helpers for template slots, remembered inputs, recents and the palette search.

import type { Slot, Template } from "../../api/types";

export type SlotValue = string | { ref: string; name?: string };
export type SlotValues = Record<string, SlotValue>;

export const isImageSlot = (s: Slot): boolean => s.kind !== "text";

export const slotLabel = (s: Slot): string => s.label ?? s.name;

/** A slot the user must fill before the template can run (no default to fall back on). */
export function mustFill(slot: Slot, values: SlotValues): boolean {
  if (!slot.required || slot.default !== null) return false;
  const v = values[slot.name];
  return v === undefined || (typeof v === "string" && v.trim() === "");
}

/** Slots still missing for a run with `values`. */
export function missingSlots(t: Pick<Template, "slots">, values: SlotValues): Slot[] {
  return t.slots.filter((s) => mustFill(s, values));
}

/** One click only runs when no required slot is open. */
export function runsWithoutInput(t: Pick<Template, "slots">, remembered: SlotValues): boolean {
  return missingSlots(t, remembered).length === 0;
}

/** The job bindings for the filled slots (empty text and unknown names are dropped). */
export function bindingsOf(
  t: Pick<Template, "slots">,
  values: SlotValues,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const slot of t.slots) {
    const v = values[slot.name];
    if (v === undefined) continue;
    if (typeof v === "string") {
      if (slot.kind === "text" && v.trim() !== "") out[slot.name] = v;
    } else if (slot.kind !== "text") out[slot.name] = { ref: v.ref };
  }
  return out;
}

// --- remembered inputs ("use last face photo") and recently used templates -------------------

const MEMORY_KEY = "p11.slot-memory";
const RECENT_KEY = "p11.recent-templates";
export const MAX_RECENT = 5;

type Memory = Record<string, SlotValues>;

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

export function recalled(templateId: string): SlotValues {
  return readJson<Memory>(MEMORY_KEY, {})[templateId] ?? {};
}

export function remember(templateId: string, values: SlotValues | null): void {
  const all = readJson<Memory>(MEMORY_KEY, {});
  if (values === null) delete all[templateId];
  else all[templateId] = values;
  localStorage.setItem(MEMORY_KEY, JSON.stringify(all));
}

export function recentIds(): string[] {
  return readJson<string[]>(RECENT_KEY, []).slice(0, MAX_RECENT);
}

/** Most recent first, no duplicates, at most MAX_RECENT. */
export function withRecent(ids: string[], id: string): string[] {
  return [id, ...ids.filter((x) => x !== id)].slice(0, MAX_RECENT);
}

export function noteRecent(id: string): string[] {
  const next = withRecent(recentIds(), id);
  localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  return next;
}

// --- palette search ---------------------------------------------------------------------------

/** Subsequence score: higher is better, null = no match. Prefix and word starts score more. */
export function fuzzyScore(query: string, text: string): number | null {
  const q = query.toLowerCase().replace(/\s+/g, "");
  const t = text.toLowerCase();
  if (!q) return 0;
  let score = 0;
  let from = 0;
  let streak = 0;
  for (const ch of q) {
    const at = t.indexOf(ch, from);
    if (at < 0) return null;
    streak = at === from ? streak + 1 : 0;
    score += 1 + streak * 2 + (at === 0 || " -_/".includes(t[at - 1] ?? "") ? 3 : 0);
    from = at + 1;
  }
  return score - t.length * 0.01;
}

export function searchTemplates(templates: Template[], query: string): Template[] {
  const scored: { t: Template; score: number }[] = [];
  for (const t of templates) {
    const hay = [t.name, t.folder, ...t.tags].join(" ");
    const score = fuzzyScore(query, hay);
    if (score !== null) scored.push({ t, score });
  }
  return scored.sort((a, b) => b.score - a.score).map((x) => x.t);
}

/** Replace `{{slot}}` placeholders by the slot defaults (to edit a template in Generate). */
export function fillDefaults(text: string, slots: Slot[]): string {
  return text.replace(/\{\{\s*([A-Za-z0-9_]+)\s*\}\}/g, (whole, name: string) => {
    const slot = slots.find((s) => s.name === name);
    return slot?.default ?? whole;
  });
}
