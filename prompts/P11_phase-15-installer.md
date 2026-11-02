# P11 Phase 15: Installer, updates & Omarchy integration

**Model:** Sonnet 5.5 (`/model claude-sonnet-5-5`) · **Depends on:** 07 · **Branch:** `phase-15-installer` · **Worktree:** `../project1111-phase-15` · **Gate:** review

## Read first
`CLAUDE.md` (Risk rule), `prompts/P11_shared-instructions.md`, spec §7, §11.2 R1, R4, R8, R15, R16, §11.3 S1, S3, S7, S9. Phase Log entries for 03, 06 and 07. `engine/engine.lock.toml`, `scripts/engine_setup.sh`. ADR-0012. The OSMods README at `/home/nick/Documents/04 Resources/OSMods/README.md` (read it before changing anything on the host).

## Goal
A new user on Omarchy or Arch with an NVIDIA GPU goes from `git clone` to an open P11 window with one script, and nothing about the system changes without their say-so. Updates and uninstall are just as simple. P11 shows up as a desktop app on Omarchy. Features from later phases (10–14) plug into the installer through the model sets and engine lock, so this phase can run beside 08–14 and Phase 16 re-checks the finished set.

## Tasks
1. **`install.sh`** (bash, `set -euo pipefail`, ShellCheck-clean, `--dry-run`, `--yes`, `--models default|full|none`, `--prefix`): detect Omarchy/Arch (`/etc/os-release`); detect the NVIDIA GPU and driver (`nvidia-smi`), print what is found; if missing or too old for the pinned torch build, **explain and link** the Omarchy/Arch NVIDIA instructions and stop (never install drivers, ADR-0012); list missing pacman packages (git, ffmpeg, base tools; *not* python, which uv provides) and ask before `sudo pacman -S --needed` (S7); install uv for the user if missing (from the distro package if available, else uv's official installer **pinned to a version and checksum**); `uv tool install` P11 from the checkout (or a venv under `~/.local/share/p11/app`) with the 3.12 interpreter (R1); run `scripts/engine_setup.sh` (pinned ComfyUI, torch check); create XDG dirs `0700` (R8); show the model set size and run `p11 models install <set>` with licence prompts; run `p11 doctor`; install the desktop entry; print how to start. Idempotent: a second run changes nothing and says so.
2. **One-liner (optional):** document `curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/v<ver>/install.sh | bash -s -- …` only for a **tag**, and have `install.sh` refuse to run from a pipe unless it verifies it was fetched from a tag (or recommend the clone path). Don't publish anything; the URL works once the repo is public (Phase 17).
3. **`p11 update`:** fetch tags, show the changelog diff, check out the latest tag (or `--to <tag>`), re-run the idempotent steps (deps, engine lock changes, new manifest entries), migrate config/templates (Phase 04 migrations), keep user data. Refuses with local modifications to the checkout.
4. **`uninstall.sh` / `p11 uninstall`:** removes the app, engine and desktop entry; asks separately about models (size shown), templates/config and outputs (default: keep outputs and templates). Never touches pacman packages it did not install without asking; prints what it leaves.
5. **Omarchy integration (R16):** a `.desktop` entry (`~/.local/share/applications/p11.desktop`) running `p11 start && p11 open`, an icon (simple original SVG), and an app-mode window like Omarchy web apps; check Hyprland behaviour (window class/title so users can add rules). If Nick wants a keybinding or a waybar/quickshell indicator, ask first and document it as an OS modification.
6. **Clean-install test:** a container test (`tests/install/`) using an Arch Linux base image with `--gpus all` (nvidia-container-toolkit is on the laptop) that runs `install.sh --yes --models none` and then `p11 doctor` and a FakeEngine smoke test; plus a full run on the laptop under a throw-away `HOME` (e.g. `HOME=$(mktemp -d)`) with `--models default`, measuring **time-to-first-image after the download** (R4).
7. **Docs:** `docs/P11_USER-GUIDE.md` install/update/uninstall, troubleshooting (driver missing, OOM, port in use, Wayland/browser quirks), laptop thermal and power notes (plugged in, performance profile).
8. **OSMods:** the desktop entry and any other host change on Nick's machine get a write-up in `/home/nick/Documents/04 Resources/OSMods/` and the README (at-a-glance row, section, "Where things live", "Last updated"), including undo steps.

## Out of scope
AUR package (follow-up), Flatpak, non-NVIDIA GPUs, non-Arch distros (documented as unsupported).

## Tests
ShellCheck in CI; `install.sh --dry-run` output snapshot; bats or pytest-driven tests of the script's detection functions with fake `os-release`/`nvidia-smi`; idempotency (two runs, second prints "nothing to do"); container clean-install test (local, marked `slow`); uninstall leaves outputs when told to.

## Acceptance criteria
- In the container: `install.sh --yes --models none` succeeds and `p11 doctor` passes the non-GPU checks (GPU checks pass with `--gpus all`).
- On the laptop under a throw-away HOME: install with the default set, then first image ≤ 5 min after the download finished (R4), recorded in `docs/P11_BENCHMARKS.md`.
- The script never runs `sudo` without listing the packages and asking (unless `--yes`), and never touches drivers or system files.
- Desktop entry launches P11 in an app window on Omarchy; OSMods entry written.

## Phase-specific docs
`docs/P11_USER-GUIDE.md`, README (install section), SECURITY (installer trust), OSMods write-up + README, `docs/P11_BENCHMARKS.md` (time-to-first-image), CHANGELOG. Then the standard close-out checklist.
