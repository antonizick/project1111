#!/usr/bin/env bash
# P11 Studio installer for Omarchy / Arch Linux with an NVIDIA GPU (spec R15, S7, ADR-0012).
#
# Usage: ./install.sh [--dry-run] [--yes] [--models SET[,SET...]|none] [--accept-licences]
#                     [--prefix DIR] [--keybinding "SUPER + ALT + I"] [--no-desktop] [--skip-engine]
#   --dry-run          print what would be done; change nothing
#   --yes              do not ask (still lists every pacman package first)
#   --models SET       model set(s) to download: default (default), face, control, full, none
#   --accept-licences  accept the licences of the chosen models (otherwise p11 asks, or fails without a TTY)
#   --prefix DIR       where the `p11` command, desktop entry and icon go (default ~/.local)
#   --keybinding KEYS  also add a Hyprland launch binding (Omarchy bindings.lua); off by default
#   --no-desktop       skip the desktop entry and icon
#   --skip-engine      skip the engine setup (containers and CI without a GPU)
# Never installs drivers, never edits system files, runs sudo only for the pacman packages it lists.
# Idempotent: a second run changes nothing and says so.
set -euo pipefail

REPO_URL="${P11_REPO_URL:-https://github.com/antonizick/project1111.git}"
MIN_DRIVER=580   # CUDA 13.x needs driver >= 580 (NVIDIA CUDA release notes, checked 2026-11-03)
UV_VERSION="0.13.0"
UV_SHA256="1468ebd5a5541121837c5a2817b9972ba6090fa6caa3d142620850a47fb75154"
UV_URL="https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-x86_64-unknown-linux-gnu.tar.gz"
NVIDIA_DOC="https://wiki.archlinux.org/title/NVIDIA"

DRY=0 YES=0 MODELS=default ACCEPT=0 PREFIX="$HOME/.local" KEYBIND="" DESKTOP=1 ENGINE=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --yes|-y) YES=1 ;;
    --models) MODELS="${2:?--models needs a value}"; shift ;;
    --accept-licences) ACCEPT=1 ;;
    --prefix) PREFIX="${2:?--prefix needs a directory}"; shift ;;
    --keybinding) KEYBIND="${2:?--keybinding needs a key combination}"; shift ;;
    --no-desktop) DESKTOP=0 ;;
    --skip-engine) ENGINE=0 ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

say() { printf '%s\n' "$*"; }
step() { printf '\n==> %s\n' "$*"; }
die() { printf 'Error: %s\n' "$1" >&2; [[ -n ${2:-} ]] && printf 'Hint: %s\n' "$2" >&2; exit "${3:-1}"; }
CHANGED=0
changed() { CHANGED=$((CHANGED + 1)); }
run() { printf '+ %s\n' "$*"; [[ $DRY == 1 ]] || "$@"; }
confirm() { # confirm "question"; --yes answers yes, no TTY answers no
  [[ $YES == 1 ]] && return 0
  [[ -t 0 ]] || return 1
  local a; read -r -p "$1 [y/N] " a; [[ $a == y || $a == Y ]]
}

# --- one-liner: only a pinned tag, never a pipe from a branch (ADR-0012) -------------------------
SELF="${BASH_SOURCE[0]:-}"
if [[ -z $SELF || ! -f $SELF ]] || [[ ! -f $(dirname "$SELF")/engine/engine.lock.toml ]]; then
  TAG="${P11_INSTALL_TAG:-}"
  [[ $TAG =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die \
    "install.sh was started without a checkout and without a release tag." \
    "Clone the repo and run ./install.sh, or set P11_INSTALL_TAG=vX.Y.Z (a tag, not a branch)." 2
  SRC="${XDG_DATA_HOME:-$HOME/.local/share}/p11/src"
  command -v git >/dev/null || die "git is required to fetch the tagged release." "sudo pacman -S git"
  say "Fetching tag $TAG from $REPO_URL into $SRC"
  [[ $DRY == 1 ]] && { say "(dry run) would clone and re-run install.sh from the tag"; exit 0; }
  rm -rf "$SRC"; git clone -q --depth 1 --branch "$TAG" "$REPO_URL" "$SRC"
  exec "$SRC/install.sh" "$@"
fi
REPO_ROOT="$(cd "$(dirname "$SELF")" && pwd)"

DATA="${P11_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/p11}"
CONFIG="${P11_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/p11}"
CACHE="${P11_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/p11}"
STATE="$DATA/install-state"
BIN_DIR="$PREFIX/bin"
export UV_TOOL_BIN_DIR="$BIN_DIR"
export PATH="$BIN_DIR:$HOME/.local/bin:$PATH"

state_get() { [[ -f $STATE ]] && sed -n "s/^$1=//p" "$STATE" | head -1 || true; }
state_set() { # key value
  [[ $DRY == 1 ]] && return 0
  mkdir -p "$DATA"; touch "$STATE"
  grep -v "^$1=" "$STATE" > "$STATE.new" || true
  echo "$1=$2" >> "$STATE.new"; mv "$STATE.new" "$STATE"
}
digest() { cat "$@" 2>/dev/null | sha256sum | cut -d' ' -f1; }

say "P11 installer: $REPO_ROOT -> prefix $PREFIX$([[ $DRY == 1 ]] && echo ' (dry run)')"

# --- 1. system -----------------------------------------------------------------------------------
step "System"
OS_RELEASE="${P11_OS_RELEASE:-/etc/os-release}"
os_id="" os_like="" os_name=""
if [[ -r $OS_RELEASE ]]; then
  os_id="$(sed -n 's/^ID=//p' "$OS_RELEASE" | tr -d '"')"
  os_like="$(sed -n 's/^ID_LIKE=//p' "$OS_RELEASE" | tr -d '"')"
  os_name="$(sed -n 's/^PRETTY_NAME=//p' "$OS_RELEASE" | tr -d '"')"
fi
if [[ $os_id != arch && $os_id != omarchy && " $os_like " != *" arch "* ]]; then
  die "This is not Arch Linux or Omarchy (found: ${os_name:-unknown})." \
      "P11 supports Arch-based systems with an NVIDIA GPU only; other distributions are not supported." 3
fi
say "OS: ${os_name:-$os_id}"
[[ $(uname -m) == x86_64 ]] || die "Only x86_64 is supported (found $(uname -m))." "" 3

command -v nvidia-smi >/dev/null || die "No NVIDIA driver found (nvidia-smi is missing)." \
  "Install the NVIDIA driver first: $NVIDIA_DOC. P11 never installs drivers." 3
gpu_line="$(nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>/dev/null | head -1 || true)"
[[ -n $gpu_line ]] || die "nvidia-smi found no GPU." "Check the driver (reboot after an update): $NVIDIA_DOC" 3
driver="$(cut -d, -f2 <<<"$gpu_line" | tr -d ' ')"
say "GPU: $gpu_line"
if (( ${driver%%.*} < MIN_DRIVER )); then
  die "NVIDIA driver $driver is too old for the pinned PyTorch (CUDA 13 needs driver ${MIN_DRIVER} or newer)." \
      "Update the driver yourself: $NVIDIA_DOC. P11 never installs drivers." 3
fi
say "Driver $driver >= $MIN_DRIVER: ok"

# --- 2. packages (pacman, asked first, S7) ---------------------------------------------------------
step "System packages"
need=()
for p in git ffmpeg curl xdg-utils; do
  pacman -Q "$p" >/dev/null 2>&1 || need+=("$p")
done
if [[ ! -f $REPO_ROOT/src/p11/web/index.html ]]; then
  command -v node >/dev/null && command -v npm >/dev/null || need+=(nodejs npm)
fi
if ! command -v uv >/dev/null && pacman -Si uv >/dev/null 2>&1; then need+=(uv); fi
if ((${#need[@]})); then
  say "Missing pacman packages: ${need[*]}"
  if [[ $DRY == 1 ]]; then
    say "(dry run) would run: sudo pacman -S --needed ${need[*]}"
  elif confirm "Install them now with sudo pacman -S --needed ${need[*]}?"; then
    sudo pacman -S --needed "${need[@]}"; changed
  else
    die "Required packages are missing." "Run: sudo pacman -S --needed ${need[*]}  then re-run ./install.sh" 4
  fi
else
  say "All required packages are installed."
fi

# --- 3. uv ----------------------------------------------------------------------------------------
step "uv"
if command -v uv >/dev/null; then
  say "uv: $(uv --version) ($(command -v uv))"
elif [[ $DRY == 1 ]]; then
  say "(dry run) would install uv $UV_VERSION from $UV_URL (SHA-256 $UV_SHA256) into $BIN_DIR"
else
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
  curl -fsSL -o "$tmp/uv.tgz" "$UV_URL"
  echo "$UV_SHA256  $tmp/uv.tgz" | sha256sum -c - >/dev/null || die "uv download failed its checksum." "" 5
  mkdir -p "$BIN_DIR"; tar xzf "$tmp/uv.tgz" -C "$tmp"
  install -m755 "$tmp"/uv-*/uv "$tmp"/uv-*/uvx "$BIN_DIR/"; changed
  say "installed uv $UV_VERSION into $BIN_DIR"
fi

# --- 4. private directories (R8) --------------------------------------------------------------------
step "Directories"
for d in "$CONFIG" "$DATA" "$CACHE"; do
  if [[ -d $d && $(stat -c %a "$d") == 700 ]]; then say "ok  $d"; else
    run mkdir -p "$d"; run chmod 700 "$d"; changed
  fi
done

# --- 5. frontend + app -------------------------------------------------------------------------------
step "P11 application"
if [[ ! -f $REPO_ROOT/src/p11/web/index.html ]]; then
  if [[ $DRY == 1 ]]; then say "(dry run) would build the frontend (npm ci && npm run build)"; else
    (cd "$REPO_ROOT/frontend" && npm ci --no-audit --no-fund && npm run build); changed
  fi
fi
app_sum="$(digest "$REPO_ROOT/pyproject.toml" "$REPO_ROOT/uv.lock")"
if [[ $(state_get app) == "$app_sum:$REPO_ROOT" && -x $BIN_DIR/p11 ]]; then
  say "p11 already installed ($BIN_DIR/p11)"
else
  run uv tool install --quiet --force --editable --python 3.12 --managed-python "$REPO_ROOT"
  state_set app "$app_sum:$REPO_ROOT"; state_set prefix "$PREFIX"; changed
fi
P11="$BIN_DIR/p11"; [[ -x $P11 || $DRY == 1 ]] || P11="$(command -v p11)"

# --- 6. engine ---------------------------------------------------------------------------------------
step "Engine (pinned ComfyUI)"
if [[ $ENGINE == 0 ]]; then
  say "skipped (--skip-engine)"
else
  eng_sum="$(digest "$REPO_ROOT/engine/engine.lock.toml" "$REPO_ROOT/engine/requirements.lock.txt" \
             "$REPO_ROOT"/engine/custom_nodes/*/__init__.py "$REPO_ROOT/engine/extra_model_paths.yaml.tmpl")"
  if [[ $(state_get engine) == "$eng_sum" && -d $DATA/engine/ComfyUI/.git ]]; then
    say "engine already set up at the pinned commit"
  else
    if [[ $DRY == 1 ]]; then "$REPO_ROOT/scripts/engine_setup.sh" --dry-run; else
      "$REPO_ROOT/scripts/engine_setup.sh"; state_set engine "$eng_sum"; changed
    fi
  fi
fi

# --- 7. models ---------------------------------------------------------------------------------------
step "Models ($MODELS)"
if [[ $MODELS == none ]]; then
  say "skipped (--models none); install later with: p11 models install default"
elif [[ $DRY == 1 && ! -x $P11 ]]; then
  say "(dry run) would show the size and run: p11 models install ${MODELS//,/ }"
else
  IFS=',' read -r -a sets <<<"$MODELS"
  for s in "${sets[@]}"; do
    plan="$("$P11" models install "$s" --dry-run --json 2>&1)" || die "Unknown model set '$s'." "Use default, face, control, full or none." 2
    bytes="$(sed -n 's/.*"download_bytes": *\([0-9]*\).*/\1/p' <<<"$plan" | head -1)"
    if [[ ${bytes:-0} == 0 ]]; then say "model set '$s': nothing to download"; continue; fi
    say "model set '$s': $(head -1 <<<"$plan")"
    if [[ $s == face || $s == full ]]; then
      say "Note: the face set includes InsightFace models that are for non-commercial research only."
    fi
    [[ $DRY == 1 ]] && { say "(dry run) would run: p11 models install $s"; continue; }
    flags=(); [[ $ACCEPT == 1 ]] && flags+=(--accept-licences)
    if ! confirm "Download model set '$s' now?"; then say "skipped; run: p11 models install $s"; continue; fi
    "$P11" models install "$s" "${flags[@]}" || die "Model set '$s' is not fully installed." \
      "Re-run ./install.sh (downloads resume), or add --accept-licences after reading: p11 models licences" 6
    changed
  done
fi

# --- 8. desktop entry (R16) --------------------------------------------------------------------------
step "Desktop entry"
if [[ $DESKTOP == 0 ]]; then say "skipped (--no-desktop)"; else
  apps="$PREFIX/share/applications"; icons="$PREFIX/share/icons/hicolor/scalable/apps"
  icon_dst="$icons/p11.svg"; desk_dst="$apps/p11.desktop"
  want="$(sed -e "s#@P11_BIN@#$BIN_DIR/p11#g" -e "s#@ICON@#$icon_dst#g" "$REPO_ROOT/assets/desktop/p11.desktop.tmpl")"
  if [[ -f $icon_dst ]] && cmp -s "$REPO_ROOT/assets/desktop/p11.svg" "$icon_dst" \
     && [[ -f $desk_dst && $(cat "$desk_dst") == "$want" ]]; then
    say "desktop entry already installed ($desk_dst)"
  else
    run mkdir -p "$apps" "$icons"
    run install -m644 "$REPO_ROOT/assets/desktop/p11.svg" "$icon_dst"
    if [[ $DRY == 1 ]]; then say "+ write $desk_dst"; else printf '%s\n' "$want" > "$desk_dst"; fi
    command -v update-desktop-database >/dev/null && [[ $DRY == 0 ]] && update-desktop-database "$apps" 2>/dev/null || true
    changed
  fi
fi

# --- 9. optional Hyprland binding ----------------------------------------------------------------------
if [[ -n $KEYBIND ]]; then
  step "Hyprland keybinding ($KEYBIND)"
  bl="${HYPRLAND_BINDINGS:-$HOME/.config/hypr/bindings.lua}"
  if [[ -f $bl ]] && grep -q 'P11 Studio launch' "$bl"; then say "binding already present in $bl"
  elif [[ -f $bl ]] && grep -qiF "\"$KEYBIND\"" "$bl"; then
    die "$KEYBIND is already bound in $bl." "Pick another combination with --keybinding." 7
  elif [[ -f $bl ]]; then
    if [[ $DRY == 1 ]]; then say "(dry run) would append to $bl"; else
      cp "$bl" "$bl.bak.p11.$(date +%s)"
      printf '\n-- P11 Studio launch (added by P11 install.sh; remove this line to undo)\no.bind("%s", "P11 Studio", "%s open")\n' "$KEYBIND" "$BIN_DIR/p11" >> "$bl"
      changed; say "added; check with: hyprctl reload && hyprctl configerrors"
    fi
  else say "no $bl: skipped (not an Omarchy Lua config)"; fi
fi

# --- 10. doctor ---------------------------------------------------------------------------------------
step "Doctor"
if [[ $DRY == 1 ]]; then say "(dry run) would run: p11 doctor"
elif [[ $ENGINE == 0 ]]; then "$P11" doctor --quick || say "(engine skipped: engine/model errors are expected)"
elif ! "$P11" doctor; then
  if [[ $MODELS == none ]]; then say "(no models installed yet: model errors are expected)"
  else die "p11 doctor reported errors." "Fix them, then re-run ./install.sh" 8; fi
fi

echo
if [[ $DRY == 1 ]]; then say "Dry run finished: nothing was changed."
elif [[ $CHANGED == 0 ]]; then say "Nothing to do: P11 is already installed and up to date."
else say "P11 installed ($CHANGED step(s) changed)."; fi
say "Start it with:  p11 open     (or launch \"P11 Studio\" from the app menu)"
say "Update:  p11 update    Uninstall:  p11 uninstall"
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) say "Note: add $BIN_DIR to your PATH.";; esac
