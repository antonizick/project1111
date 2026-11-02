#!/usr/bin/env bash
# Run the whole bake-off matrix (Phase 03). Restores the starting power profile on any exit (H8).
# Usage: scripts/bench/all.sh [stage ...]   (default: base presets vram stability thermal)
set -uo pipefail
cd "$(dirname "$0")/../.."
prev="$(powerprofilesctl get)"
trap 'powerprofilesctl set "$prev"; echo "[all] power restored to $prev"' EXIT
trap 'exit 143' TERM INT
LEAD="${LEAD:-realvisxl5_lightning}"
stages=("$@"); [[ ${#stages[@]} -gt 0 ]] || stages=(base presets vram stability thermal)
for st in "${stages[@]}"; do
  echo "[all] stage $st $(date '+%F %T %Z')"
  case "$st" in
    base) uv run python -m scripts.bench.run base ;;
    presets) uv run python -m scripts.bench.run presets --prompts p01 ;;
    vram) uv run python -m scripts.bench.run vram --models "$LEAD" --modes dynamic,classic,lowvram --chains "${CHAIN:-model}" ;;
    stability) uv run python -m scripts.bench.run stability --models "$LEAD" --n 50 --preset 2560x1440 --chain "${CHAIN:-model}" ;;
    thermal) uv run python -m scripts.bench.run thermal --models "$LEAD" --minutes 10 --preset 1920x1080 --chain "${CHAIN:-model}" ;;
    *) echo "unknown stage $st"; exit 2 ;;
  esac || echo "[all] stage $st failed with $?"
done
echo "[all] done $(date '+%F %T %Z')"
