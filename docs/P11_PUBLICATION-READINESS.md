# P11 Publication Readiness (for Phase 17)

**Last updated:** @@TS@@ (Phase 16 licence audit). Target: v1.0.0 as an annotated tag plus a GitHub release **on the private repo** (H13, ADR-0016). Making the repo public is out of scope for v1.0.0.

## Verdict
**No blocker for the private v1.0.0 release.** Nothing third-party is vendored that would stop P11's own code being MIT, no weights are in git, and every licence restriction is flagged where the owner sees it. Phase 17 still asks Nick "go?" before tagging (the planned stop).

## What was audited
| Area | Finding |
|---|---|
| P11's own code | MIT (`LICENSE`, holder Nick Antonizick, H15) |
| Python runtime dependencies (41, `uv export --no-dev`) | all permissive: MIT, BSD-2/3-Clause, Apache-2.0, ISC, PSF-2.0, MIT-CMU (Pillow); `certifi` is MPL-2.0 (file-level copyleft, used unmodified: no obligation beyond keeping its notice) |
| Shipped frontend bundle | `react`, `react-dom`, `scheduler`: MIT. Dev tooling (not shipped): 236 packages, MIT/Apache-2.0/ISC/BSD/BlueOak-1.0.0/MPL-2.0/MIT-0/CC0/CC-BY-4.0 (`caniuse-lite` data); minimatch 11.0.4 is BlueOak-1.0.0 (permissive) |
| Engine | ComfyUI v0.43.0 (GPL-3.0) is installed separately by `scripts/engine_setup.sh` from its pinned commit, never vendored (`git ls-files` holds no ComfyUI file); P11 talks to it over HTTP |
| Custom node | `engine/custom_nodes/p11_ipadapter`: P11's own MIT code, written from the checkpoint layout (no copied code: no third-party copyright or GPL marker; ADR-0031). It runs inside a GPL program, and MIT is GPL-compatible |
| Fonts | five OFL-1.1 fonts in `assets/fonts/` with their licence files beside them (`OFL-*.txt`) and SHA-256 in `fonts.json` |
| Models (21 manifest entries) | none in git (`.gitignore` covers weights; gitleaks + the large-file hook); all 21 are listed in `THIRD_PARTY_NOTICES.md` with licence and a commercial-use flag, also in the manifest, the installer prompt and the Models page |

## Restrictions to keep visible (not blockers)
- **InsightFace `arcface-w600k-r50` and `inswapper-128`: non-commercial research only.** In the optional `face` set, never `default`; the installer and Models page require an explicit acknowledgement (verified on a TTY in Phase 16: both prompts shown, "no" aborts, "yes" records `licences.toml`; without a TTY the install stops and names `--accept-licences`). The owner makes logos and game assets: **face swap output is not cleared for commercial use.**
- **CreativeML OpenRAIL-M checkpoints** (Juggernaut XL v9, the default set's Quality model, and Realistic Vision V6.0 in `full`): use-based restrictions travel with the weights; flagged in THIRD_PARTY_NOTICES. Check each SDXL checkpoint's own row there before commercial use.
- **If the repo is ever made public** (out of scope for v1.0.0): re-check that the README's install path names a tag; nothing else in the tree changes.

## Open items for the Phase 17 review (H10, H12)
Listed in the plan's Phase 16 Phase Log entry ("For the owner's review" and "Deferred").
