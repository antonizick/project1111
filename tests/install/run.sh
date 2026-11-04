#!/usr/bin/env bash
# Clean-install test (slow, local): install.sh in a stock Arch container with the host GPU.
#   tests/install/run.sh [--no-gpu]
# Runs install.sh --yes --models none, p11 doctor, a second install (must say "Nothing to do"),
# and a FakeEngine smoke test (serve --fake, /healthz). Needs docker + nvidia-container-toolkit.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GPU=(--gpus all)
[[ ${1:-} == --no-gpu ]] && GPU=()
IMAGE=p11-install-test
docker build -q --pull --no-cache -t "$IMAGE" "$REPO/tests/install" >/dev/null
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
(cd "$REPO" && git ls-files -co --exclude-standard -z | tar --null -T - -cf "$tmp/src.tar")
docker run --rm "${GPU[@]}" -v "$tmp/src.tar:/src.tar:ro" "$IMAGE" bash -euo pipefail -c '
  mkdir p11 && tar -xf /src.tar -C p11 && cd p11
  ./install.sh --yes --models none ${P11_INSTALL_ARGS:-}
  export PATH="$HOME/.local/bin:$PATH"
  p11 doctor --quick || true
  out="$(./install.sh --yes --models none ${P11_INSTALL_ARGS:-})"
  echo "$out" | tail -4
  grep -q "Nothing to do" <<<"$out"
  p11 start --fake
  sleep 1
  tok="$(cat "$(p11 status --token-file)")"; : "$tok"
  p11 status
  p11 stop
  test -f ~/.local/share/applications/p11.desktop
  ./uninstall.sh --yes
  ! test -e ~/.local/share/p11/engine
  echo CLEAN-INSTALL-OK
'
