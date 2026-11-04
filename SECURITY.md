# Security policy

## Reporting a vulnerability
Please report vulnerabilities privately through a [GitHub security advisory](https://github.com/antonizick/project1111/security/advisories/new). Do not open a public issue, and do not attach personal images, videos or model files to a report.

P11 is pre-release. Expect an acknowledgement within a few days; fixes are tracked in [`CHANGELOG.md`](CHANGELOG.md).

## Scope
In scope:
- **The local service:** the Studio API and the engine process (binding to `127.0.0.1` only, Host/Origin/token checks, CSP, upload validation, path handling).
- **The installer and updater** (`install.sh`, `uninstall.sh`, `p11 update`).
- **Model downloads:** hash and size verification, file-format policy (safetensors by default), download sources.
- **Supply chain:** pinned ComfyUI and custom-node commits, locked Python and npm dependencies, CI and pre-commit tooling.
- **Templates and image metadata:** template import (schema validation, generated file names, no path traversal) and the recipe embedded in PNGs, including metadata stripping on export. Templates never store bound photos (Save as Template drops uploads and turns them into empty inputs); remembered slot inputs are upload IDs and text in the browser's `localStorage`, never file contents. An inpaint template saved with "Keep this mask" stores the mask shape (a small greyscale PNG, decoded with Pillow and checked as a PNG before use), never the photo.
- **The face-swap NSFW target guard**, which must not be bypassable (spec S5).

Out of scope: vulnerabilities in third-party engines or models themselves (report those upstream; we will update our pin), and attacks that already require local code execution as the same user.

## Baseline
The security and privacy baseline is spec Amendments S1–S10 in [`docs/P11_SPECIFICATION.md`](docs/P11_SPECIFICATION.md). Secrets are scanned with gitleaks in pre-commit and CI. Never commit secrets, tokens, `.env` files, model weights or personal media.

## Model files
Model weights are code-adjacent: pickle-based formats (`.ckpt`, `.pt`, `.pth`, `.bin`) can execute arbitrary code when loaded. P11 (ADR-0021, spec S4):
- downloads curated models only over HTTPS from the pinned commit named in `models/manifest.toml`, and deletes any file whose size or SHA-256 differs;
- identifies user-added files by content and refuses pickle formats unless `--allow-pickle` is given for that file (with a warning); `p11 doctor` keeps warning about such files;
- loads only tensor-only formats: `.safetensors`, `.gguf` and (for curated, hash-pinned entries that exist only in that form, such as the segmentation model) `.onnx` — an ONNX graph holds tensors and cannot execute code the way a pickle can;
- reads optional tokens only from `~/.config/p11/secrets.toml` with mode `0600`, sends each token only to its own host (never across a redirect to another host) and never logs it.
Report a manifest entry whose source changed, or a way to load an unverified file, as a vulnerability.

## The local service (Phase 07)
P11 Studio is a web server on your own machine, and any web page you visit can try to talk to it. It defends itself as follows (ADR-0022, spec S1, S2, S6, S8):
- It listens on `127.0.0.1` only; the engine (ComfyUI) also listens on `127.0.0.1` and is never reachable from the browser.
- **DNS rebinding:** requests whose `Host` is not `127.0.0.1:<port>` or `localhost:<port>` are refused.
- **Cross-site requests:** a request from another origin (`Origin`, `Sec-Fetch-Site`) that would change anything, or that reads `/api`, is refused; the API sends no CORS headers.
- **Session token:** a new random token per Studio launch, stored `0600` in `$XDG_RUNTIME_DIR/p11/`. `p11 open` passes the browser a one-time launch code (valid 2 minutes) in the URL fragment, never the token. API calls carry the token in a header; the `HttpOnly`, `SameSite=Strict` cookie is accepted for reads only. Other programs running as **your** user can read the token file; that is out of scope (they could read your pictures too).
- **Content-Security-Policy** `default-src 'self'` (no remote scripts, styles, fonts or frames), `nosniff`, `no-referrer`, no framing.
- **Uploads** are checked by content, not name: images are decoded and re-saved as PNG without EXIF (GPS included); videos are probed by ffprobe, limited to known containers and codecs, and re-muxed without metadata. Stored names are generated; the browser only ever sees an opaque ID.
- **Request size limits:** 1 MB for API calls, 64 MB per image, 1 GB per video.
- **Logs** (`~/.cache/p11/logs/studio.log` and `engine.log`, both `0600`) never contain the token, launch codes, prompt text or file contents at the default level; `--debug` adds prompt text but still redacts the token.
- FastAPI's built-in OpenTelemetry hooks are switched off; nothing is sent anywhere.

**The UI (Phase 08)** loads nothing from the network: no CDN, fonts or analytics (Playwright fails the build if a page request leaves `127.0.0.1:<port>`). Downloads are made from an in-memory `blob:` URL. "Delete" moves files into P11's own trash folder (`~/.local/share/p11/trash/`, `0700`); "Empty trash" deletes only that folder, after a confirmation.

Report a way to reach the API from a web page, read another user's outputs, get a file outside P11's folders, or find the token in a log as a vulnerability.

## The face-swap content boundary (Phase 12, spec S5)

Generation is unfiltered (A5): P11 has no safety checker, prompt filter or blocklist. Face-swap is
the one path that can turn a picture of a real, identifiable person into sexual imagery, so **every
face swap carries an NSFW check on its target and refuses sexual or nude images**.

- The check runs **twice per swap** (target before the swap, result before it is saved) and **once
  more at submit time** whenever the target already exists as a file, so the UI, the API, a template
  run and (in Phase 13) every video frame are covered by the same code path.
- **Two classifiers, both required, either refusing is enough**: Marqo's ViT-tiny and Freepik's
  EVA02, both hash-pinned ONNX models with fixed thresholds (ADR-0029). The thresholds and model
  IDs are constants in `src/p11/media/nsfw.py`.
- **There is no switch.** No setting, environment variable, API parameter, recipe field or template
  field names the guard; `FaceSwap` deliberately has no guard field, and `tests/unit/test_media_faces.py`
  greps the source for one.
- **It fails closed.** If either classifier is missing or unreadable, the swap does not run.
- **P11 ships no feature, preset or template that puts a real person's face into sexual content, and
  nothing that sexualizes minors.** This is not open to a phase's judgment or to a change request.

The refusal is a plain-English problem ("P11 does not put faces onto nude or sexual images. Choose a
different image.") with no score, no probability and no hint about how to get past it. Test fixtures
for the guard are synthetic and non-explicit (S6): a generated image with magenta corners for the
stub, and P11-generated portraits for the real classifiers. Never add an explicit image to the repo
or to fixtures.

**Video face-swap carries the same guard (Phase 13).** Every frame the video pipeline swaps goes through the same two-classifier check on its target and on its result, and a sampled pre-pass (about one frame per second plus scene changes) refuses the whole clip before any swapping; a refusal stops the job and deletes its scratch frames. There is no switch (ADR-0034).

**Likeness beyond the swap (Phase 16, ADR-0037).** A **face reference** (Use as reference → The
person or character) also keeps a real person recognisable, and so does any later edit of a swapped
picture. P11 therefore runs the same two-classifier check on: the output of a face reference; every
step that follows a face swap or face reference in the same run; and every job whose input is a
gallery picture made that way (the picture's sidecar records it). Plain generation and style
references stay unfiltered (A5). The check models must be installed or these jobs refuse.

**Edits of uploaded photos (Phase 17b, ADR-0038).** An uploaded file is an unflagged input, so an
unfiltered edit of a real person's photo would be a new path to the same boundary. When a photo edit
(**Start from a photo** on Generate), an inpaint or a background replacement edits an *uploaded*
image in which the face detector finds a face, every output goes through the same two-classifier
check and is flagged `likeness`, so later edits of it are checked as well. Without the `face` model
set such an edit is refused before it is queued: "Editing an uploaded photo needs the face safety
models: run `p11 models install face`". Pictures P11 made itself without a likeness, and plain text
to image, stay unfiltered (A5). The detector runs on the CPU (about 100 ms on a 1920x1080 photo) and
there is no switch.

**Residual risks (Phase 16 threat model, `docs/P11_THREAT-MODEL.md`).** The engine port
(`127.0.0.1:8188`) has no authentication, so any program running as your user can drive ComfyUI
directly, outside P11's checks; such a program could equally read your pictures, so this is the same
privilege boundary as the token file. A picture exported with metadata stripped and uploaded again
is a new input with no likeness record; since Phase 17b that photo is still face-checked before it is edited, so the gap is limited to faces the detector misses (small, turned away, stylised). The classifiers can miss.

**Using other people's likenesses.** The Studio shows a one-line notice in the face panel: "Use
faces of people who agreed." Face photos are private data (S6): uploads are stored under
`~/.local/share/p11/` with `0700`, EXIF/GPS is stripped on upload, and nothing is written to the
repo, fixtures or logs. Video clips are handled the same way (the stored copy is a metadata-free
remux, S8), and their extracted frames live in `~/.cache/p11/jobs/<job>/` (`0700`) only while a job
runs — they are deleted when it finishes or is cancelled, and a refused clip's frames are deleted
immediately.

## The installer (Phase 15, spec S7, ADR-0012, ADR-0036)
- `install.sh` never installs or changes GPU drivers and never edits files outside your HOME. It runs `sudo` only for `pacman -S --needed` with the package list printed first (and asks, unless you pass `--yes`).
- It refuses to run from a pipe unless `P11_INSTALL_TAG` names a `vX.Y.Z` release tag; it then clones that tag and runs the script from the clone. Prefer cloning and reading the script.
- The only thing it downloads outside the pinned engine and model manifest is uv, and only when the distribution has no package: a fixed release URL checked against a SHA-256 in the script.
- Private directories are created with mode `0700` (R8). `--keybinding` appends one line to your Hyprland `bindings.lua` (after a backup) and refuses a combination that is already bound.
- `p11 update` only fast-forwards the checkout to a release tag, and only when tracked files are unmodified. Check tags you do not trust before updating.
- `uninstall.sh` deletes models, settings and images only when you say so.
