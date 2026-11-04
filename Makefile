# P11 developer entry points. `make setup && make check` is what PHX and CI run on a clean clone.
SHELL := /bin/bash
.DEFAULT_GOAL := help

GITLEAKS_VERSION := 8.30.1
GITLEAKS_SHA256  := 551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb
SHELLCHECK_VERSION := 0.11.0
SHELLCHECK_SHA256  := 8c3be12b05d5c177a04c29e3c78ce89ac86f1595681cab149b65b97c4e227198
TOOLS_BIN        := $(CURDIR)/.tools/bin
export PATH      := $(TOOLS_BIN):$(HOME)/.local/bin:$(PATH)

.PHONY: help setup tools fmt lint typecheck test gpu-test e2e build audit secrets check clean

help:
	@echo "make setup|tools|fmt|lint|typecheck|test|gpu-test|e2e|build|audit|secrets|check"

setup: tools
	uv sync --locked
	cd frontend && npm ci

# Tools with no PyPI/npm package, installed at user level, pinned by version and SHA-256 (spec H4).
tools:
	@if gitleaks version 2>/dev/null | grep -qx '$(GITLEAKS_VERSION)'; then \
	  echo "gitleaks $(GITLEAKS_VERSION) already installed"; \
	else \
	  set -euo pipefail; mkdir -p $(TOOLS_BIN); d=$$(mktemp -d); \
	  curl -fsSL -o $$d/g.tgz https://github.com/gitleaks/gitleaks/releases/download/v$(GITLEAKS_VERSION)/gitleaks_$(GITLEAKS_VERSION)_linux_x64.tar.gz; \
	  echo "$(GITLEAKS_SHA256)  $$d/g.tgz" | sha256sum -c -; \
	  tar xzf $$d/g.tgz -C $$d gitleaks; install -m755 $$d/gitleaks $(TOOLS_BIN)/gitleaks; rm -rf $$d; \
	fi
	@if shellcheck --version 2>/dev/null | grep -q '^version: $(SHELLCHECK_VERSION)$$'; then \
	  echo "shellcheck $(SHELLCHECK_VERSION) already installed"; \
	else \
	  set -euo pipefail; mkdir -p $(TOOLS_BIN); d=$$(mktemp -d); \
	  curl -fsSL -o $$d/s.txz https://github.com/koalaman/shellcheck/releases/download/v$(SHELLCHECK_VERSION)/shellcheck-v$(SHELLCHECK_VERSION).linux.x86_64.tar.xz; \
	  echo "$(SHELLCHECK_SHA256)  $$d/s.txz" | sha256sum -c -; \
	  tar xJf $$d/s.txz -C $$d; install -m755 $$d/shellcheck-v$(SHELLCHECK_VERSION)/shellcheck $(TOOLS_BIN)/shellcheck; rm -rf $$d; \
	fi

fmt:
	uv run ruff format .
	uv run ruff check --fix .
	cd frontend && npx prettier --write .

lint:
	uv run ruff format --check .
	uv run ruff check .
	shellcheck install.sh uninstall.sh scripts/*.sh tests/install/*.sh
	cd frontend && npm run lint

typecheck:
	uv run mypy
	cd frontend && npm run typecheck

# Coverage gate (>= 90 %): the pure core (Phase 04), the engine adapter + telemetry (Phase 05),
# the model manager (Phase 06) and the Studio API, jobs, uploads and lifecycle (Phase 07).
COV := --cov=p11.recipe --cov=p11.outputs --cov=p11.templates --cov=p11.engine --cov=p11.gpu \
  --cov=p11.models --cov=p11.api --cov=p11.jobs --cov=p11.media --cov=p11.lifecycle \
  --cov=p11.doctor --cov=p11.logs --cov-report=term --cov-fail-under=90

test:
	uv run pytest -m "not gpu and not e2e" $(COV)
	cd frontend && npm test

gpu-test:
	uv run pytest -m gpu

e2e: build
	cd frontend && npx playwright install chromium && npm run e2e

# Through webbundle: it bakes the build id into the bundle and stamps it (ADR-0043).
build:
	uv run python -m p11.webbundle build

audit:
	uv export --locked --no-emit-project --format requirements-txt -o /tmp/p11-audit-reqs.txt >/dev/null
	uv run pip-audit --strict --disable-pip -r /tmp/p11-audit-reqs.txt
	cd frontend && npm audit --omit=dev

secrets:
	gitleaks git --redact --verbose .

check: lint typecheck test audit secrets

clean:
	rm -rf src/p11/web frontend/node_modules .venv .tools .pytest_cache .mypy_cache .ruff_cache
