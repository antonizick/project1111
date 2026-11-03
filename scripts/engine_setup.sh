#!/usr/bin/env bash
# Install (or re-verify) the pinned headless ComfyUI engine for P11.
# Pins come from engine/engine.lock.toml; dependencies from engine/requirements.lock.txt (hashes).
# Idempotent: a second run only re-checks. Never touches the host Python (R1) or system files (S7).
#
# Usage: scripts/engine_setup.sh [--relock] [--no-check] [--dry-run]
#   --relock    regenerate engine/requirements.lock.txt from ComfyUI's requirements at the pin
#   --no-check  skip the GPU torch check (sm_75, fp16 matmul/conv)
#   --dry-run   print what would be done
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK_TOML="$REPO_ROOT/engine/engine.lock.toml"
REQ_LOCK="$REPO_ROOT/engine/requirements.lock.txt"

DATA="${P11_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/p11}"
ENGINE_DIR="$DATA/engine"
COMFY="$ENGINE_DIR/ComfyUI"
VENV="$ENGINE_DIR/venv"
MODELS="$DATA/models"

RELOCK=0 CHECK=1 DRY=0
for a in "$@"; do
  case "$a" in
    --relock) RELOCK=1 ;;
    --no-check) CHECK=0 ;;
    --dry-run) DRY=1 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

run() { echo "+ $*"; [[ $DRY == 1 ]] || "$@"; }

# Minimal TOML reader for `key = "value"` inside a [section].
toml() {
  awk -v sec="[$1]" -v key="$2" '
    /^\[/ { insec = ($0 == sec) }
    insec && $1 == key { sub(/^[^=]*= *"/, ""); sub(/".*$/, ""); print; exit }
  ' "$LOCK_TOML"
}

COMFY_REPO="$(toml comfyui repo)"
COMFY_SHA="$(toml comfyui commit)"
PYVER="$(toml python version)"
TORCH_INDEX="$(toml torch index_url)"
TORCH_VER="$(toml torch torch)"
TV_VER="$(toml torch torchvision)"
[[ -n $COMFY_SHA && -n $PYVER && -n $TORCH_VER ]] || { echo "cannot read $LOCK_TOML" >&2; exit 1; }
command -v uv >/dev/null || { echo "uv is required (https://docs.astral.sh/uv/)" >&2; exit 1; }

echo "P11 engine: ComfyUI $COMFY_SHA, Python $PYVER, torch $TORCH_VER -> $ENGINE_DIR"

# 1. ComfyUI checkout at the pinned commit.
run mkdir -p "$ENGINE_DIR"
if [[ -d $COMFY/.git ]] && [[ $(git -C "$COMFY" rev-parse HEAD) == "$COMFY_SHA" ]] \
   && [[ -z $(git -C "$COMFY" status --porcelain --untracked-files=no) ]]; then
  echo "ComfyUI already at $COMFY_SHA"
else
  if [[ ! -d $COMFY/.git ]]; then
    run git init -q "$COMFY"
    run git -C "$COMFY" remote add origin "$COMFY_REPO"
  fi
  run git -C "$COMFY" fetch -q --depth 1 origin "$COMFY_SHA"
  run git -C "$COMFY" -c advice.detachedHead=false checkout -q --force FETCH_HEAD
  [[ $DRY == 1 ]] || [[ $(git -C "$COMFY" rev-parse HEAD) == "$COMFY_SHA" ]] \
    || { echo "checkout is not at $COMFY_SHA" >&2; exit 1; }
fi

# 2. Hash-locked requirements (S3).
if [[ $RELOCK == 1 || ! -f $REQ_LOCK ]]; then
  tmp="$(mktemp)"
  { echo "torch==$TORCH_VER"; echo "torchvision==$TV_VER"; cat "$COMFY/requirements.txt"; } > "$tmp"
  run uv pip compile -q --python-version "$PYVER" --python-platform x86_64-manylinux_2_28 \
    --generate-hashes --index-strategy unsafe-best-match \
    --extra-index-url "$TORCH_INDEX" -o "$REQ_LOCK" "$tmp"
  rm -f "$tmp"
fi

# 3. Separate uv venv with the pinned Python (ADR-0008).
if [[ ! -x $VENV/bin/python ]] || ! "$VENV/bin/python" -c "import sys; assert '%d.%d' % sys.version_info[:2] == '$PYVER'" 2>/dev/null; then
  run uv venv -q --python "$PYVER" --managed-python "$VENV"
fi
run uv pip sync -q --python "$VENV/bin/python" --require-hashes \
  --index-strategy unsafe-best-match --extra-index-url "$TORCH_INDEX" "$REQ_LOCK"

# 4. Model folders outside the checkout (R8) and extra_model_paths.yaml.
for d in checkpoints loras vae controlnet ipadapter clip_vision upscale facerestore faceswap \
         facedetect classifiers preprocess segmentation embeddings; do
  run mkdir -p "$MODELS/$d"
done
yaml="$ENGINE_DIR/extra_model_paths.yaml"
if [[ $DRY == 0 ]]; then
  sed "s#@MODELS@#$MODELS#g" "$REPO_ROOT/engine/extra_model_paths.yaml.tmpl" > "$yaml.new"
  if cmp -s "$yaml.new" "$yaml"; then rm "$yaml.new"; else mv "$yaml.new" "$yaml"; echo "wrote $yaml"; fi
fi

# 4b. P11's own custom node pack (S3, ADR-0031): copied from this repo, digest checked against
#     engine.lock.toml. It is the only pack the engine is allowed to load (its launch flags).
PACK_NAME="p11_ipadapter"
PACK_SRC="$REPO_ROOT/engine/custom_nodes/$PACK_NAME"
PACK_ENTRY="__init__.py"
PACK_SHA="$(awk -F'"' -v n="name = \"$PACK_NAME\"" '$0 == n {found=1} found && /^sha256 = / {print $2; exit}' "$LOCK_TOML")"
[[ -n $PACK_SHA ]] || { echo "no sha256 for $PACK_NAME in $LOCK_TOML" >&2; exit 1; }
pack_sum="$(sha256sum "$PACK_SRC/$PACK_ENTRY" | cut -d' ' -f1)"
if [[ $pack_sum != "$PACK_SHA" ]]; then
  echo "engine/custom_nodes/$PACK_NAME/$PACK_ENTRY is not the copy engine.lock.toml pins." >&2
  echo "Review the change and update the sha256 there (S3)." >&2
  exit 1
fi
run mkdir -p "$COMFY/custom_nodes/$PACK_NAME"
if [[ $DRY == 0 ]]; then
  dest="$COMFY/custom_nodes/$PACK_NAME/$PACK_ENTRY"
  if [[ -f $dest ]] && cmp -s "$PACK_SRC/$PACK_ENTRY" "$dest"; then
    echo "$PACK_NAME already installed"
  else
    cp "$PACK_SRC/$PACK_ENTRY" "$dest.new" && mv "$dest.new" "$dest"
    echo "installed $PACK_NAME into $COMFY/custom_nodes/"
  fi
fi

# 5. Torch check on the GPU (ADR-0009): CUDA, sm_75, real fp16 kernels, no CPU fallback.
if [[ $CHECK == 1 && $DRY == 0 ]]; then
  "$VENV/bin/python" - <<'PY'
import sys, warnings
warnings.simplefilter("error")  # "no kernel image" / unsupported-arch warnings become failures
import torch
assert torch.cuda.is_available(), "torch.cuda.is_available() is False"
cap = torch.cuda.get_device_capability(0)
assert cap == (7, 5), f"expected sm_75, got {cap}"
assert "sm_75" in torch.cuda.get_arch_list(), f"sm_75 not in {torch.cuda.get_arch_list()}"
a = torch.randn(1024, 1024, device="cuda", dtype=torch.float16)
b = (a @ a).float()
conv = torch.nn.Conv2d(4, 64, 3, padding=1).cuda().half()
c = conv(torch.randn(1, 4, 128, 128, device="cuda", dtype=torch.float16))
attn = torch.nn.functional.scaled_dot_product_attention(*(torch.randn(1, 8, 256, 64, device="cuda", dtype=torch.float16),) * 3)
torch.cuda.synchronize()
assert b.is_cuda and c.is_cuda and attn.is_cuda
assert torch.isfinite(b).all() and torch.isfinite(c).all() and torch.isfinite(attn).all()
print(f"torch check OK: torch {torch.__version__}, CUDA {torch.version.cuda}, "
      f"{torch.cuda.get_device_name(0)} sm_{cap[0]}{cap[1]}, cudnn {torch.backends.cudnn.version()}")
PY
fi
echo "engine ready: $COMFY"
