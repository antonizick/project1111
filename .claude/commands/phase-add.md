---
description: Inject a new phase into the Project_1111 plan from a change request (e.g. /phase-add after 15a <request>, /phase-add path/to/request.md)
argument-hint: "[after NN] [change-request file | pasted request]  (no argument: it interviews you)"
---
You are **planning** (not building) a new phase for Project_1111. Argument: `$ARGUMENTS`.
The output is a phase that Nick can run later with `/phase <ID>`: a row in the plan, a self-contained prompt,
a planning Phase Log entry, ADRs for any decisions made now, the vault note, and one planning commit on `main`.
**Write no product code, and do not claim the phase.** Its status stays `⬜ Not started`.

## 0. Preconditions
- The main checkout (`/home/nick/Work/project1111`) is on `main` and `git status --short P11_IMPLEMENTATION_PLAN.md prompts docs/P11_DECISIONS.md`
  prints nothing. If not, stop and tell Nick (another agent may be mid-claim).
- Read `CLAUDE.md`, `P11_IMPLEMENTATION_PLAN.md` (from `main`, including the Phase Log and owner questions),
  `prompts/P11_shared-instructions.md`, `docs/P11_DECISIONS.md` (the list of ADR titles plus any the request touches),
  the Amendments section of `docs/P11_SPECIFICATION.md`, and the **most recent phase prompt** as a style reference.

## 1. Intake
**No argument (`$ARGUMENTS` is empty): interview Nick before anything else.** Never guess the request.
1. Show a compact table of the plan from `main` (ID, name, status, model) and the next free letter after each
   phase that is not complete.
2. Ask, in plain text, for **what the new phase must deliver**: one bullet per change, ideally "today: … →
   want: …", plus the reason and how Nick will check it is done. Say that Nick can instead paste a filled
   `prompts/P11_change-request-template.md` or give its path. Wait for the answer.
3. Ask **where it goes** with AskUserQuestion, giving 2-4 options derived from the table:
   - your recommendation first: usually after the last completed or last inserted phase, so it runs next
     and before release;
   - after a specific earlier phase whose output it builds on;
   - "as late as possible" (just before the release phase).
   In the same call, ask any owner decisions you can already see (rule 4, "Classify each open point", below).
4. Read the answers back as numbered items with the proposed ID, and continue with the steps below.

1. The request is either a file path (read it in full, plus everything it attaches or links) or pasted text.
   The recommended shape is `prompts/P11_change-request-template.md`, but any free text works.
2. Split it into numbered items. Keep Nick's wording: the prompt will quote it under "Nick's request (verbatim intent, TIMESTAMP)".
3. **Ground every item in the code.** Find the files, functions, routes, templates, settings, ADRs and docs
   it touches, and note what already exists, what is half-built, and anything that contradicts the request
   (for example a UI hint promising a feature that does not exist). This becomes the prompt's
   "What exists (verified TIMESTAMP; re-check before relying on it)" section, with `path:symbol` references.
4. Classify each open point:
   - **Owner decisions** (licensing, publishing, privacy, anything public or hard to reverse, or a real
     product choice with no conventional default): ask Nick **once**, in one batched question round, with an
     Option | Pros | Cons table or options and a recommendation. Decided now → an ADR. Deliberately left
     open → a row in the plan's owner questions table with "Needed by: Phase <ID>"; the prompt must say to
     stop and ask if it is still open.
   - **Everything else:** choose a sensible default and write it into the prompt as the default, so the
     phase agent can follow it or justify a change in its ADR.

## 2. Placement and ID
- **Never renumber or edit completed phases.** Insert the work **after phase P** with ID = P plus the next free
  lower-case letter (`09` → `09a`; after `15a` → `15b`; after `09a` → `09b`). Two digits plus one letter;
  no decimals. The letter only orders phases; it does not mean "small".
- P is the phase whose output the new work builds on. If Nick wrote `after NN`, use it; otherwise propose P
  and say why. For feedback rounds after hardening, P is the last round (ADR "interim tuning rounds").
- **Depends on:** P plus anything else the work needs.
- **Rewire dependents:** every not-started phase that must include this work (always the release phase) now
  depends on the new ID. Change its row *and* its prompt header. Never rewire a `🔄` or `✅` phase.
- If a `🔄 In progress` phase touches the same files, warn Nick about the overlap and the merge order.
- Several unrelated requests may become several phases. If they can run in parallel, give them separate
  letters with the same P and say so in the plan.

## 3. Model, size and slug
- Model, per the plan's "Model rationale": the strongest model for subtle correctness, state, parsing,
  security, prompt engineering or complex interactive UI; the balanced model for well-specified UI, CRUD,
  content, packaging and docs. State the reason in one line in the Phase Log planning entry.
- One focused session: one goal and about 5-10 tasks. If it is bigger, split it.
- Slug: short and kebab-case. File `prompts/P11_phase-<ID>-<slug>.md`, branch `phase-<ID>-<slug>`, worktree
  `../project1111-phase-<ID>`.

## 4. Write
1. **Prompt** `prompts/P11_phase-<ID>-<slug>.md`, in the same structure as the other prompts:
   - header line (model and `/model` command, Depends on, branch, worktree, and `· **Gate:** <value>` if the plan has a Gate column);
   - context (one paragraph: why this phase exists);
   - **Read first**;
   - **Nick's request (verbatim intent, TIMESTAMP)**;
   - **Decisions already made** (ADR links);
   - **Goal**;
   - **What exists (verified TIMESTAMP)**;
   - **Tasks**, numbered and concrete, naming files, interfaces and the security controls to honour;
   - **Out of scope**;
   - **Tests**;
   - **Acceptance criteria**, verifiable in the real app;
   - **Phase-specific docs**;
   - "Then the standard close-out checklist."
2. **`P11_IMPLEMENTATION_PLAN.md`:**
   - add the row in ID order with `⬜ Not started` and, if the table has a `Gate` column, a Gate cell (`auto` unless the phase publishes or needs a human check: `review`; or needs Nick's hands: `owner`). Put the same value in the prompt header as `· **Gate:** <value>`;
   - rewire dependents;
   - update the dependency graph and the "Last updated" line;
   - add any owner questions;
   - add a Phase Log entry `### TIMESTAMP: Planning: phase <ID> inserted (Planned)`: a first bullet `- **Timeline:** started <TS> · finished <TS>` (*started* is `date` taken at the beginning of this planning session, *finished* is `date` taken just before the commit), then the request in brief, the
     scope, the placement and model rationale, the decisions taken, and the other files changed.
3. **ADRs** in `docs/P11_DECISIONS.md` for decisions made during intake (append, add the row to the index table at the top, and mark any ADR it supersedes).
   Spec amendments are normally left to the phase; add one now only if Nick changed the product definition.
4. **Later prompts:** edit any not-started prompt whose assumptions change (at least the release phase's
   "depends on" and anything about screenshots, notices or docs).
5. **Vault note** `/home/nick/Documents/02 Projects/P11 Implementation Plan.md`: add the row (`⬜ Not started`) and a timestamped log line.
## 5. Verify and commit
- Every link in the new row and prompt resolves (`ls`); each table row has exactly one status icon; each
  prompt's "Depends on" matches the table; no `{{` remains; `/phase status` logic would list the new phase
  in the right order.
- Refresh the timeline: `python3 scripts/phase_timeline.py --write --vault-note "/home/nick/Documents/02 Projects/P11 Implementation Plan.md"` (adds this planning session to the Planning lane).
- Commit only the planning files, the timeline SVG included, to `main`: `git commit -m "docs(plan): add phase <ID> (<title>)" -- <files>`.
  This is **not** a claim. Push `main` afterwards if a remote exists (standing git authority).

## Naming and timestamps
Use the project prefix `P11_` on every new project document (the prompt file is
`prompts/P11_phase-<ID>-<slug>.md`). Every date you write (Phase Log heading, ADR rows and
**Recorded** line, "Last updated", the prompt's "verbatim intent" and "verified" lines, the vault log) is a
timestamp, `YYYY-MM-DD HH:MM TZ`, taken from `date '+%Y-%m-%d %H:%M %Z'` when you write it.

## 6. Report to Nick
- The new row (ID, name, model, depends on).
- Decisions recorded (ADR numbers) and any open questions.
- Anything surprising found while grounding.
- How to launch it: `/model <id>`, then `/phase <ID>`. Mention whether it can run in parallel with anything.
