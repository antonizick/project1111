#!/usr/bin/env bash
# Remove P11 Studio. Also run by `p11 uninstall`.
#
# Usage: ./uninstall.sh [--dry-run] [--yes] [--models] [--config] [--outputs] [--prefix DIR]
# Always removed: the p11 command, the engine (ComfyUI + its venv), the desktop entry and icon, caches.
# Asked about separately (kept by default, with their size shown):
#   --models   the downloaded models         (~/.local/share/p11/models)
#   --config   settings, templates, licence acknowledgements (~/.config/p11) and the gallery index
#   --outputs  generated images and sidecars (~/Pictures/P11)
# --yes answers "no" to the three questions above unless the flag is given. pacman packages are
# never removed (P11 cannot know which ones you needed before).
set -euo pipefail

DRY=0 YES=0 DEL_MODELS=0 DEL_CONFIG=0 DEL_OUT=0 PREFIX=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --yes|-y) YES=1 ;;
    --models) DEL_MODELS=1 ;;
    --config) DEL_CONFIG=1 ;;
    --outputs) DEL_OUT=1 ;;
    --prefix) PREFIX="${2:?--prefix needs a directory}"; shift ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

DATA="${P11_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/p11}"
CONFIG="${P11_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/p11}"
CACHE="${P11_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/p11}"
PICTURES="${P11_PICTURES_DIR:-${XDG_PICTURES_DIR:-$HOME/Pictures}/P11}"
STATE="$DATA/install-state"
if [[ -z $PREFIX ]]; then
  PREFIX="$(sed -n 's/^prefix=//p' "$STATE" 2>/dev/null | head -1 || true)"; PREFIX="${PREFIX:-$HOME/.local}"
fi
BIN_DIR="$PREFIX/bin"
export PATH="$BIN_DIR:$HOME/.local/bin:$PATH"

size() { [[ -e $1 ]] && du -sh "$1" 2>/dev/null | cut -f1 || echo 0; }
ask() { # ask "question" -> keep by default
  [[ $YES == 1 || ! -t 0 ]] && return 1
  local a; read -r -p "$1 [y/N] " a; [[ $a == y || $a == Y ]]
}
rm_path() {
  [[ -e $1 || -L $1 ]] || return 0
  printf '+ rm -rf %s\n' "$1"; [[ $DRY == 1 ]] || rm -rf -- "$1"
}
kept=()

# Stop the Studio (and the engine it started) first.
if command -v p11 >/dev/null && [[ $DRY == 0 ]]; then p11 stop || true; fi

echo "Removing the app, engine and desktop entry"
if command -v uv >/dev/null && uv tool list 2>/dev/null | grep -q '^p11 '; then
  printf '+ uv tool uninstall p11\n'; [[ $DRY == 1 ]] || UV_TOOL_BIN_DIR="$BIN_DIR" uv tool uninstall p11
fi
rm_path "$DATA/engine"
rm_path "$PREFIX/share/applications/p11.desktop"
rm_path "$PREFIX/share/icons/hicolor/scalable/apps/p11.svg"
command -v update-desktop-database >/dev/null && [[ $DRY == 0 ]] && update-desktop-database "$PREFIX/share/applications" 2>/dev/null || true
rm_path "$CACHE"
rm_path "$DATA/src"
rm_path "$STATE"

# Models
if [[ -d $DATA/models ]]; then
  if [[ $DEL_MODELS == 1 ]] || ask "Delete the downloaded models ($(size "$DATA/models"))?"; then rm_path "$DATA/models"
  else kept+=("models: $DATA/models ($(size "$DATA/models"))"); fi
fi
# Config, templates, gallery index and other data
if [[ -d $CONFIG || -f $DATA/gallery.db ]]; then
  if [[ $DEL_CONFIG == 1 ]] || ask "Delete settings, templates and the gallery index ($(size "$CONFIG"))?"; then
    rm_path "$CONFIG"; rm_path "$DATA/gallery.db"; rm_path "$DATA/jobs.db"; rm_path "$DATA/inputs"
  else kept+=("settings and templates: $CONFIG"); fi
fi
# Outputs
if [[ -d $PICTURES ]]; then
  if [[ $DEL_OUT == 1 ]] || ask "Delete generated images ($(size "$PICTURES"))?"; then rm_path "$PICTURES"
  else kept+=("generated images: $PICTURES ($(size "$PICTURES"))"); fi
fi
[[ $DRY == 1 ]] || rmdir "$DATA" 2>/dev/null || true

echo
[[ $DRY == 1 ]] && echo "Dry run: nothing was removed."
if ((${#kept[@]})); then echo "Kept:"; printf '  %s\n' "${kept[@]}"; fi
echo "Not touched: pacman packages, the NVIDIA driver, any Hyprland keybinding you added"
echo "(remove the 'P11 Studio launch' line from ~/.config/hypr/bindings.lua), and this checkout."
