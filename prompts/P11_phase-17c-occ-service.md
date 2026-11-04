# P11 Phase 17c: P11 in the Omarchy Control Center (OCC)

**Model:** Sonnet 5.5 (`/model claude-sonnet-5-5`) · **Depends on:** 17 · **Branch:** `phase-17c-occ-service` · **Worktree:** `../project1111-phase-17c` · **Gate:** auto

Nick runs his resource-hungry local services from OCC (`~/Work/OCC_OmarchyControlCenter`, `Super + Alt + T`): a localhost dashboard with a card per service (health, CPU, memory, uptime, Start / Stop / Restart / Logs / Open). P11 Studio, which holds the GPU while it works, is not on it yet. This phase gives P11 an OCC card. OCC is config-driven (one `[[service]]` block in `~/.config/occ/services.toml`, no OCC code change), plus a small token-free busy signal on P11's side. Opening the Studio from the card needs a new OCC feature, `open_exec`, which is planned in the OCC repo as **OCC phase 10a** (ADR-0039). Use it if that phase is done; otherwise leave it out. Can run in parallel with 17a and 17b.

## Read first
`CLAUDE.md` (Risk rule: this phase edits a file outside the repo, named here), `prompts/P11_shared-instructions.md`, spec §11 Amendments (S1, S2, R8). Phase Log entries for 07 and 15. ADR-0013, ADR-0022 (launch codes, token), ADR-0036 (installer), **ADR-0039**. In the OCC repo (read only, except as task 5 says): `CLAUDE.md`, `docs/user-guide/adding-a-service.md`, `config/templates/cli-web-app.toml`, `config/services.example.toml` (the field reference at the top, the MeetingMaster3 block as the closest worked example) and `OCC_IMPLEMENTATION_PLAN.md` (is phase 10a `✅ Complete`?). Vault: `/home/nick/Documents/04 Resources/OSMods/OSMODs README.md`, `OCC Omarchy Control Center.md`, `P11 Installer and Desktop Entry.md`.

## Nick's request (verbatim intent, received by 2026-11-04 07:40 CST)
"ALSO Add P11 Operations to the OCC framework and launcher on my Omarchy instance"

## Decisions already made
- **ADR-0039:** P11 is an OCC `transient` service running `p11 serve` in the foreground (OCC wraps it as `occ-p11.service`), with health on `/healthz`, a busy signal readable without the session token, journal logs and a Stop confirmation. P11's launch-code security stays as is (no reusable or token-free UI URL). The card's **Open** uses OCC's `open_exec = ["~/.local/bin/p11", "open"]` once OCC phase 10a ships it; until then the card has no Open and `Super + Alt + I` / the app launcher open P11.
- Placement: 17c after 17, parallel with 17a/17b; release v1.0.1 in 17d (ADR-0040).

## Goal
After `occ quit` and `occ`, the OCC dashboard shows a **P11 Studio** card that is Stopped / Starting / Healthy / Distressed correctly; Start launches the Studio (which still starts the engine on the first job and stops it when idle); Stop and Restart ask first when a generation is running; Logs show the Studio's journal; a P11 already started with `p11 start`, `p11 open` or `Super + Alt + I` is recognised as External; and Open (if OCC 10a is complete) opens the authenticated Studio window.

## What exists (verified 2026-11-04 07:40 CST; re-check before relying on it)
- `~/.local/bin/p11` → `~/.local/share/uv/tools/p11/bin/p11` (editable `uv tool` install, ADR-0036). `p11 serve` runs in the foreground on `127.0.0.1:8111` (`src/p11/config.py:Settings.studio_port`, engine 8188) and writes the lifecycle state, so `p11 open`, `p11 status` and `p11 stop` see an OCC-started Studio. It refuses to start when the port is taken. `p11 start` spawns `[sys.executable, "-m", "p11", "serve"]` (`src/p11/lifecycle.py:start_background`), so a hand-started Studio's command line ends in `-m p11 serve`.
- `GET /healthz` is token-free and returns `{"status": "ok", "version": …}` (`src/p11/api/app.py:create_app`). Everything under `/api` needs the session token (`src/p11/api/security.py`), so OCC cannot read `/api/jobs` or `/api/system` for a busy badge.
- The UI needs a one-time launch code (`p11 open` mints it and opens `omarchy-launch-or-focus-webapp`-style), so a plain `open_url` lands on "Open P11 with `p11 open`".
- OCC fields used here (from `config/services.example.toml`): `id, name, description, kind = "transient", exec, workdir, start_grace, port, health {url, expect_json_field, expect_json_value}, busy {url, json_path, busy_values}, match {cmdline_regex}, logs [{kind = "journal", error_regex}], confirm {busy}, requires, details`. `exec[0]` must be absolute (`~` is expanded). The live config is `~/.config/occ/services.toml`, mode `600` (OCC refuses anything group/world-writable); OCC reads it only at start (ADR-0033 in OCC). Ports 7340–7359 are OCC's own. Other cards: bookmarks, meetingmaster3, ollama, open-webui, rclone, prometheus, chessloop.
- Ollama (another card) shares the 8 GB GPU; both loaded at once can OOM P11 (P11 retries in low-VRAM mode, ADR-0020).

## Tasks
1. **Busy signal on `/healthz`** (P11 code, `src/p11/api/app.py`): add `"busy": "idle" | "busy"` and `"queue": {"running": 0|1, "waiting": n}` from the job queue. No prompts, file names, IDs or other job details (S6); still token-free, loopback-only (S1/S2 unchanged). Unit test plus an API test; update the API docs and the threat model (one line: what the unauthenticated endpoint reveals).
2. **The service block.** Back up the live config first (`cp -p ~/.config/occ/services.toml ~/.config/occ/services.toml.bak.p11.<epoch>`), then append a commented block following the MeetingMaster3 example, with defaults:
   `id = "p11"`, `name = "P11 Studio"`, `description = "Local image generation (P11 Studio + headless ComfyUI)"`, `kind = "transient"`, `exec = ["~/.local/bin/p11", "serve"]`, `workdir = "~"`, `start_grace` from a measured cold start plus margin, `port = 8111`, `health = { url = "http://127.0.0.1:8111/healthz", expect_json_field = "status", expect_json_value = "ok" }`, `busy = { url = "http://127.0.0.1:8111/healthz", json_path = "busy", busy_values = ["busy"] }`, `confirm = { busy = "A generation is running; it will be cancelled." }` (match P11's actual stop behaviour), `match = { cmdline_regex = '(^|[ /])(p11|-m p11) serve( |$)' }` (test it against both launch forms with `occ check -v` and a hand-started Studio), `logs = [{ kind = "journal", error_regex = '\b(ERROR|CRITICAL)\b|^Traceback' }]` (check P11's real log format; P11 also logs to `~/.cache/p11/logs/`, so consider a `file` log source if the journal is thin), `requires = ["~/.local/bin/p11"]`. If OCC phase 10a is `✅ Complete` on OCC's `main`, add `open_exec = ["~/.local/bin/p11", "open"]` (field name as OCC 10a shipped it); otherwise add it as a comment naming OCC 10a and record a follow-up. Keep the file mode `600`.
3. **Check:** `occ check` exits 0 with no new warning; `occ check -v` shows the regexes matching. Do not start, stop or restart any other card's service (OCC CLAUDE.md rule). Relaunching OCC plays a voice cue: in an interactive session tell Nick before `occ quit` / `occ`; in hands-off mode do not relaunch, and leave it as a step in the final message.
4. **Live test** (with the GPU lock free, no other P11 running): Start from the card (or `systemd-run`-equivalent via OCC's API if the window cannot be driven) → Healthy within `start_grace`; Busy appears during a FakeEngine or small real job; Stop asks and then stops the whole cgroup, including the engine child (`pgrep -f ComfyUI` empty afterwards, `p11 status` says not running); External shows for a `p11 start` Studio. Leave P11 stopped at the end (CLAUDE.md: never leave an engine running).
5. **No OCC repo changes.** Do not edit anything in `~/Work/OCC_OmarchyControlCenter` (OCC phase 10a owns its code; its owner question 9 about showing the real service list is still open, so `config/services.example.toml` stays as is). The P11 block lives only in the live config, P11's docs and OSMods.
6. **Docs:** a new "Run P11 from OCC" section in `docs/P11_USER-GUIDE.md` (the block, how to reload OCC, what Busy means, Open vs `Super + Alt + I`); the OSMods record (task 7).
7. **OSMods (mandatory, host change):** update `P11 Installer and Desktop Entry.md` (or add `P11 in OCC.md`) and `OCC Omarchy Control Center.md` with the block, the backup path, how to undo (delete the block, restore the backup, `occ quit && occ`), and the verified results; update `OSMODs README.md` (at-a-glance table, section, "Where things live", "Last updated").

## Out of scope
OCC code changes (OCC phase 10a owns `open_exec`); a systemd unit file for P11 or enabling anything at login; changing P11's launch-code security; the 17a/17b work; the release (17d).

## Tests
Unit/API tests for the new `/healthz` fields (idle, running, waiting; no job details leak); `make check`. The live checks in tasks 3–4, written into the Phase Log with times.

## Acceptance criteria
- `occ check` clean with the P11 block; the dashboard (after Nick relaunches OCC) shows P11 Studio with correct states, Busy during a job, a confirmed Stop that leaves no engine process, Logs that show Studio lines, External for a hand-started Studio.
- Open works from the card if OCC 10a is complete; otherwise the follow-up is recorded in the plan and the commented line is in the config.
- OSMods and the user guide describe it, including undo.

## Phase-specific docs
CHANGELOG `[Unreleased]` → Added (`/healthz` busy fields, OCC integration guide); user guide; `docs/P11_ARCHITECTURE.md` (health endpoint); `docs/P11_THREAT-MODEL.md`; OSMods. Then the standard close-out checklist.
