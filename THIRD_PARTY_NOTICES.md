# Third-party notices

P11 distributes none of the components below. They are installed separately, pinned by commit or SHA-256, and used under their own licences. "Flags" records restrictions such as non-commercial use. Versions, commits, licences and URLs are verified at the source before they are entered.

## Engine components
To be filled by Phase 03.

| Name | Version / commit | Licence | URL | Flags |
|---|---|---|---|---|

## Custom nodes
To be filled by Phase 03 (adding a node needs an ADR).

| Name | Version / commit | Licence | URL | Flags |
|---|---|---|---|---|

## Python and npm dependencies
Direct runtime dependencies as locked in Phase 02 (versions and licences read from the installed package metadata on 2026-11-02; the full locked set is audited in Phase 16).

| Name | Version | Licence | URL | Flags |
|---|---|---|---|---|
| fastapi | 0.162.0 | MIT | https://pypi.org/project/fastapi/ | none |
| uvicorn | 0.54.0 | BSD-3-Clause | https://pypi.org/project/uvicorn/ | none |
| pydantic | 2.14.2 | MIT | https://pypi.org/project/pydantic/ | none |
| pydantic-settings | 2.16.2 | MIT | https://pypi.org/project/pydantic-settings/ | none |
| typer | 0.27.3 | MIT | https://pypi.org/project/typer/ | none |
| httpx | 0.28.1 | BSD-3-Clause | https://pypi.org/project/httpx/ | none |
| websockets | 17.4 | BSD-3-Clause | https://pypi.org/project/websockets/ | none |
| pillow | 13.0.0 | MIT-CMU (HPND-style) | https://pypi.org/project/pillow/ | none |
| react, react-dom | 19.3.1 | MIT | https://www.npmjs.com/package/react | none |
| vite | 8.3.5 | MIT | https://www.npmjs.com/package/vite | none |

## Models
To be filled by Phase 06 (manifest) and audited in Phase 16. Weights are never committed or redistributed.

| Name | Version / SHA-256 | Licence | URL | Flags (e.g. non-commercial, OpenRAIL-M) |
|---|---|---|---|---|

## Development tooling
| Name | Version | Licence | URL | Flags |
|---|---|---|---|---|
| gitleaks | 8.30.1 | MIT | https://github.com/gitleaks/gitleaks | none |
| pre-commit-hooks | v6.0.0 | MIT | https://github.com/pre-commit/pre-commit-hooks | none |
| pytest, pytest-asyncio, pytest-cov | 9.2.0 / 1.4.1.post1 / 7.1.0 | MIT / Apache-2.0 / MIT | https://pypi.org/ | dev only |
| ruff, mypy, pip-audit | 0.17.3 / 2.4.1 / 2.10.1 | MIT / MIT / Apache-2.0 | https://pypi.org/ | dev only |
| vitest, jsdom, Testing Library, eslint, typescript-eslint, prettier, typescript | 5.1.0 / 30.1.3 / 16.3.3 / 10.14.0 / 8.72.1 / 3.9.10 / 6.0.3 | MIT (typescript: Apache-2.0) | https://www.npmjs.com/ | dev only |
| @playwright/test | 1.64.1 | Apache-2.0 | https://www.npmjs.com/package/@playwright/test | dev only; downloads Chromium to `~/.cache/ms-playwright` |
