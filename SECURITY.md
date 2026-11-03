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
- **Templates and image metadata:** template import (schema validation, generated file names, no path traversal) and the recipe embedded in PNGs, including metadata stripping on export.
- **The face-swap NSFW target guard**, which must not be bypassable (spec S5).

Out of scope: vulnerabilities in third-party engines or models themselves (report those upstream; we will update our pin), and attacks that already require local code execution as the same user.

## Baseline
The security and privacy baseline is spec Amendments S1–S10 in [`docs/P11_SPECIFICATION.md`](docs/P11_SPECIFICATION.md). Secrets are scanned with gitleaks in pre-commit and CI. Never commit secrets, tokens, `.env` files, model weights or personal media.

## Model files
Model weights are code-adjacent: pickle-based formats (`.ckpt`, `.pt`, `.pth`, `.bin`) can execute arbitrary code when loaded. P11 (ADR-0021, spec S4):
- downloads curated models only over HTTPS from the pinned commit named in `models/manifest.toml`, and deletes any file whose size or SHA-256 differs;
- identifies user-added files by content and refuses pickle formats unless `--allow-pickle` is given for that file (with a warning); `p11 doctor` keeps warning about such files;
- reads optional tokens only from `~/.config/p11/secrets.toml` with mode `0600`, sends each token only to its own host (never across a redirect to another host) and never logs it.
Report a manifest entry whose source changed, or a way to load an unverified file, as a vulnerability.
