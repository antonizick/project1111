# P11 Threat Model

**Last updated:** 2026-11-03 20:29 CST (Phase 16). Scope: P11 Studio, its engine, the installer and updater, and the model downloads on one single-user Omarchy laptop. Companion documents: [`SECURITY.md`](../SECURITY.md) (policy and user-facing controls), spec §11.3 (S1–S10), ADR-0013, ADR-0022, ADR-0029, ADR-0034, ADR-0037.

## 1. Assets
| Asset | Where | Why it matters |
|---|---|---|
| Face photos, background photos, videos (uploads) | `~/.local/share/p11/inputs/` (`0700`) | Personal data of real people (S6); a face plus an unfiltered generator is the abuse case S5 exists for |
| Outputs and their recipes (PNG chunks, sidecars, gallery DB) | `~/Pictures/P11/` (`0700`), `~/.local/share/p11/` | Private pictures; the recipe reveals prompts |
| Video scratch frames | `~/.cache/p11/jobs/<job>/` (`0700`) | Thousands of frames of a real person, kept only while a job can resume |
| Session token and launch codes | `$XDG_RUNTIME_DIR/p11/studio.token` (`0600`), memory | Full control of the Studio API |
| Optional model-host tokens | `~/.config/p11/secrets.toml` (`0600`) | Account credentials (S9) |
| The machine itself | | Code execution through a malicious model, node, dependency or parser bug |
| The S5 content boundary | `src/p11/media/nsfw.py`, `p11.recipe.likeness` | Must not be bypassable through any P11 path |

## 2. Trust boundaries
```
 web pages in the browser ──(HTTP, any origin)──▶ ① Studio 127.0.0.1:8111 ──▶ ② engine 127.0.0.1:8188
                                                    │                           (ComfyUI, no auth)
 other local processes ───────────────────────────────────────────────────────┘
                                                    ├──▶ ③ model hosts (HTTPS, Hugging Face)
 ./install.sh, p11 update ──▶ ④ pacman (sudo, printed list), uv, git tags, PyPI, npm, PyTorch index
```
1. **Browser ↔ Studio.** Untrusted: any page the user visits can send requests to `127.0.0.1`. The Studio's own page is trusted once it holds the token.
2. **Studio ↔ engine.** The engine trusts whatever reaches its port; P11 is its only intended client.
3. **P11 ↔ model hosts.** Hosts and the network are untrusted; manifest hashes are the trust anchor.
4. **Installer ↔ system.** The user runs it; it must stay inside HOME except for the confirmed pacman list.

## 3. Threats, mitigations and residual risk
| # | Threat | Mitigation (where) | Verified (Phase 16) | Residual risk |
|---|---|---|---|---|
| T1 | **DNS rebinding**: a page on `evil.example` re-points its name to 127.0.0.1 and reads the API | Host allowlist `127.0.0.1:<port>`/`localhost:<port>`, 421 otherwise (`api/security.py`) | `test_api_security.py::test_bad_host_is_refused_everywhere` (4 hosts); live check §4 | none known |
| T2 | **CSRF** from a malicious page (form POST, `fetch` with `no-cors`, `<img>` GET) | Token required for every `/api` call; cookie accepted for safe methods only; foreign `Origin`, `null` origin and any `Sec-Fetch-Site` other than `same-origin`/`none` refused for writes and API reads | `test_hardening.py::test_other_local_origins_are_refused` (null origin, another 127.0.0.1 port, same-site, cross-site) | none known |
| T3 | **Token theft**: in a URL, a log, a Referer | Token never in a URL (one-time launch code in the fragment, 2 min); `no-referrer`; `logs.register_secret` redacts it; access log omits query strings | studio.log scanned (§4); `test_logs.py` | other processes of the same user can read the token file (out of scope, SECURITY.md) |
| T4 | **Malformed auth headers** crash the middleware | Constant-time compare on bytes (non-ASCII no longer raises `TypeError` → 500) | **Found and fixed in Phase 16**: `test_hardening.py::test_a_non_ascii_token_is_a_401_not_a_crash` | none |
| T5 | **Launch-code flooding** | Minting needs the token; codes expire after 120 s; at most 16 outstanding (oldest dropped) | `test_hardening.py::test_outstanding_launch_codes_are_capped` | none |
| T6 | **Local process drives the engine port** (ComfyUI has no auth): runs graphs, reads `/view`, uses `p11_ipadapter` with the face adapter without the S5 guard | Engine binds 127.0.0.1 only, never exposed to the browser (CSP `connect-src 'self'`, the Studio never proxies it); engine `--disable-all-custom-nodes` except P11's own pack; no face-swap node in the engine at all (swaps run in P11, ADR-0028) | `ss -ltnp` (§4); Phase 05 gpu test checks the listener | **Accepted residual risk**: any process running as the user can reach port 8188. Such a process can already read every picture and run any code, so this is the same privilege; documented here and in SECURITY.md |
| T7 | **S5 bypass**: face swap without the guard | Guard at submit time, before the swap, on the result; per video frame + sampled pre-pass; fails closed; no switch (ADR-0029, ADR-0034) | §5 path-by-path review | classifiers can miss (two models, OR rule) |
| T8 | **S5 bypass through likeness without a swap**: face reference (IP-Adapter Plus Face), a later step reworking a swap, a later job editing a swapped image | **Found and fixed in Phase 16** (ADR-0037): likeness-carrying graphs, every later step of the run, and jobs whose inputs came from a likeness run pass the guard; sidecar flag `likeness` | `tests/unit/test_likeness_guard.py` (12 tests); Phase 17b: `tests/unit/test_photo_edit.py` (upload face rule) | **Narrowed in Phase 17b** (ADR-0038): an *uploaded* photo edited by a photo edit, Inpaint or Background is face-checked (YuNet) and, with a face, every output passes the guard and is flagged `likeness`, so a re-uploaded likeness picture is caught when it shows a face; without the `face` set such an edit is refused. Remaining: a face the detector misses (small, turned away, heavily stylised) is not flagged; text to image stays unfiltered (A5) |
| T9 | **Malicious model file** (pickle RCE) | Safetensors/GGUF/hash-pinned ONNX only; pickle refused unless opted in per file; manifest SHA-256 verified, mismatch deleted (S4, ADR-0021) | `test_models_formats.py`, `test_models_cli.py::test_add_pickle_refused_then_allowed` | ONNX runtime parser bugs (pinned onnxruntime 1.31.1) |
| T10 | **Compromised custom node or engine update** | ComfyUI pinned by commit, the one node pack is P11's own source pinned by SHA-256; installer refuses a different copy; no ComfyUI-Manager (S3) | §4: engine `426f5ee` clean tree, node digest matches the lock | an upstream compromise inside the pinned commit (reviewed at pin time only) |
| T11 | **Compromised dependency** | `uv.lock` with hashes, `package-lock.json`, Dependabot, pip-audit and npm audit in `make check` | §6 scanners | zero-day in a locked dependency |
| T12 | **Path traversal** via upload names, gallery refs, template import, export | Generated IDs (`img-…`, `vid-…`), names never taken from uploads; gallery paths resolved and checked `is_relative_to` the outputs root; template slugs validated | `test_media.py`, `test_templates*.py`, `test_hardening.py::test_path_spellings_still_need_the_token` | none known |
| T13 | **Parser bugs** in Pillow / ffprobe / ffmpeg on hostile uploads | Content validation, size/pixel caps (64 MB, 40 MP, 12000 px; 1 GB, 600 s, 2160p), decompression-bomb warning as error, re-encode/remux, timeouts on ffprobe (30 s) and remux (300 s) | **Phase 16 fuzz**: 24 crafted images, 10 crafted videos, 400 image + 30 video mutations: every input stored cleanly or refused with `UploadRejected` (`test_upload_fuzz.py`) | an unknown memory-safety bug in libpng/libjpeg/libwebp/ffmpeg (system packages; keep the OS updated) |
| T14 | **Personal data leaks** via logs, repo, fixtures | INFO logs carry no prompt text or file contents; logs `0600` (engine log fixed in Phase 16); `.gitignore` and gitleaks; fixtures synthetic | §4 log scan; gitleaks over full history | `--debug` writes prompt text by design (the user asks for it) |
| T15 | **Telemetry / unexpected egress** | No telemetry in P11, FastAPI OTel hooks off, engine `--offline` + `HF_HUB_OFFLINE`, `DO_NOT_TRACK`; no CDN | §4 egress watch; Playwright network guard on every spec | none observed |
| T16 | **Installer abuse** (pipe-to-bash of `main`, sudo beyond pacman, driver changes) | Pinned tag only for the one-liner, printed pacman list + confirmation, no driver installs, ShellCheck-clean, `--dry-run` (S7, ADR-0036) | `tests/install/run.sh` in a clean Arch container; ShellCheck in `make lint` | the user can still run an untrusted fork's script |

## 4. Live verification on the laptop (Phase 16)
- **Listeners** (`ss -ltnpu`, 2026-11-03 19:00 CST, during the GPU runs): the engine on `127.0.0.1:8188` only; the Studio (`p11 serve`) on `127.0.0.1:8111` only (Phase 07 test plus the Phase 15 install). An unrelated `python3 -m http.server` on `127.0.0.1:18213` belongs to another tool, not P11.
- **Egress**: a watcher (`ss -tunp` once a second, `~/.cache/p11/bench/qa/netwatch*.log`) recorded every socket of the benchmark Studio from 19:00 CST and of the engine process as well from 19:34 CST, with a non-loopback peer, until 20:15 CST, across the 50-run soaks, the thermal loop and the 30-minute mixed session (generate, inpaint, background, face swap, upscale, model switch): **none**. The presets stage (18:52–19:01) ran before the watcher started; Phase 03 watched the engine for 2.5 h with the same result. A 1 Hz sample can miss a sub-second connection; the engine runs `--offline` with `HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE`, and the Playwright network guard checks every UI request.
- **Host/Origin/token against the running service**: see `docs/P11_BENCHMARKS.md` → Phase 16 security checks (curl against a real `p11 serve`).
- **`/healthz` (token-free)**: returns `status`, `version`, `busy` (`idle`/`busy`) and `queue` counts (`running` 0/1, `waiting` n). It reveals that a job is in progress and how many wait — never a job id, prompt, model or file name — and it stays loopback-only behind the Host allowlist, like the rest of the service (S1/S2; Phase 17c, ADR-0039).
- **CSP**: every response, static files included, carries `default-src 'self'; … object-src 'none'; base-uri 'none'; frame-ancestors 'none'` (`test_api_security.py::test_security_headers_on_every_response`, `test_static_files_get_the_csp`, and the live curl).
- **Engine pin**: `git -C ~/.local/share/p11/engine/ComfyUI rev-parse HEAD` = `426f5eea52a7ece1dd599fff4cb6cd1f352ddd24` = `engine.lock.toml`; tracked tree clean; `custom_nodes/p11_ipadapter/__init__.py` SHA-256 `fd45ca11…b416` = lock; torch `2.14.1+cu130` = lock.
- **Lock integrity**: `uv sync --locked` and `npm ci` succeed (`make setup`).
- **Private directories**: `~/.local/share/p11`, `~/.config/p11`, `~/.cache/p11`, `~/Pictures/P11` are `0700`; `licences.toml` `0600`; `p11 doctor` "permissions: data, outputs and secrets are private".
- **Logs**: `studio.log` (202 lines) has no prompt text, no bearer token and no copy of the live token; `engine.log` names no non-loopback URL. `engine.log` was `0644` (inside the `0700` folder) and is now created `0600`.
- **Secrets**: `gitleaks git` over the full history: no leaks.

## 5. S5 bypass review, path by path
| Path | Result |
|---|---|
| UI Face view → `POST /api/jobs` | guarded (submit-time check, before-swap, result) |
| API direct submission with an edited recipe | same `Runner.validate` + `run_face_swap`; no field names the guard |
| Template import with edited steps, then run | templates run through `/api/jobs` → same path (`test_a_template_can_run_a_face_swap_and_still_hits_the_guard`) |
| Recipe migration (older documents) | `migrate()` then the same compile and runner |
| Gallery re-run / variation | `queue.submit` → same path; the parent image's likeness flag now also applies (ADR-0037) |
| Video job | per-frame `run_face_swap` (target + result) + sampled pre-pass; `GuardRefused` is not swallowed by the per-frame `FaceError` pass-through |
| Video resume (`resume_of`) | the spec hash must match the interrupted run; resumed frames are swapped through the same `run_face_swap`; the pre-pass is skipped only when it already passed for those frames |
| Server restart with queued jobs | jobs re-run through `Runner.run`, which guards inside |
| `p11 serve --fake` | the stub guard is paired with the stub swapper (no real swap can run with the stub guard) |
| Face reference (character/face mode, or a face adapter in style mode) | **was unguarded; fixed (ADR-0037)** |
| A step after a swap in the same recipe (e.g. inpaint) | **was unguarded; fixed (ADR-0037)** |
| A later edit of a swapped gallery image | **was unguarded; fixed (ADR-0037)** |
| Engine port directly | residual risk T6 |

## 6. Scanner results (Phase 16, all findings triaged)
| Tool | Scope | Result |
|---|---|---|
| ruff `S` (flake8-bandit) | `src/p11` | 34 findings, all low-risk and justified: 16 `S101` asserts (type narrowing only; none guards a security decision), 9 `S603`/`S606`/`S607` subprocess calls (argument lists, no shell; ffmpeg/ffprobe/git/nvidia-smi/install.sh), 3 `S608` (only fixed column names and `?` placeholders are interpolated), 2 `S105` (the names `TOKEN_FILE`, `TOKEN_HEADER`), 2 `S311` (`random` for seeds, not secrets) |
| bandit 1.9.4 | `src/p11` | 0 high; 3 medium = the same `S608` (justified); 38 low = the categories above plus `B404` (importing subprocess) |
| Semgrep 1.183.0 (`p/python`, `p/typescript`, `p/react`, `p/javascript`, `p/secrets`; `--metrics=off`) | `src/`, `frontend/src/`, `install.sh`, `uninstall.sh`, `scripts/`, `tests/install/` (185 files) | 4 findings, all in the developer benchmark `scripts/bench/first_image.py` (`subprocess` with an argv-supplied `--p11` path; the operator picks the binary): justified |
| pip-audit (`make audit`) | locked runtime + dev | no known vulnerabilities |
| npm audit (all, dev included) | `frontend/` | was 11 moderate (minimatch < 11.0.1 ReDoS, GHSA-g3hv-75wg-m249, via eslint/typescript-eslint, dev only) → **0** after an `overrides` pin to minimatch 11.0.4 |
| ShellCheck 0.11.0 | `install.sh`, `uninstall.sh`, `scripts/*.sh`, `tests/install/*.sh` | clean (`make lint`) |
| gitleaks 8.30.1 | full history | no leaks |

No high or critical finding is open.
