#!/usr/bin/env bash
# PHX verification command (.phx/config.toml test_command): runs on a clean clone of main
# with no installed dependencies. Before Phase 02 adds the Makefile, only the plan checks run.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/phase_timeline.py --check
if [[ ! -f Makefile ]]; then
  echo "phx_verify: no Makefile yet (Phase 02 adds it); plan checks only"
  exit 0
fi
make setup
make check
