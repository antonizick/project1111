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
- **The face-swap NSFW target guard**, which must not be bypassable (spec S5).

Out of scope: vulnerabilities in third-party engines or models themselves (report those upstream; we will update our pin), and attacks that already require local code execution as the same user.

## Baseline
The security and privacy baseline is spec Amendments S1–S10 in [`docs/P11_SPECIFICATION.md`](docs/P11_SPECIFICATION.md). Secrets are scanned with gitleaks in pre-commit and CI. Never commit secrets, tokens, `.env` files, model weights or personal media.
