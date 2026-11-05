# Canonical scene-verify commands. CI and the pre-push hook invoke these targets rather than
# restating the commands. The Python targets run inside the uv-managed workspace environment
# (.venv) against the lockfile.

SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
UV ?= uv
RUN := $(UV) run --frozen

.PHONY: setup lint format format-check typecheck test check lock-check hooks-check audit

## setup: create or update .venv from uv.lock (dev group, both workspace packages editable)
setup:
	$(UV) sync --locked --group dev

## lint: ruff check
lint:
	$(RUN) ruff check .

## format: ruff format (rewrites files)
format:
	$(RUN) ruff format .

## format-check: ruff format --check
format-check:
	$(RUN) ruff format --check .

## typecheck: mypy over both packages and the tests (scope in pyproject.toml [tool.mypy])
typecheck:
	$(RUN) mypy

## test: the full suite (no GPU, no Isaac Sim; requires_isaac tests are deselected)
test:
	$(RUN) pytest -q

## check: the fast gates (lint, format-check, typecheck, lock-check); the pre-push hook runs this
check: lint format-check typecheck lock-check

## lock-check: uv.lock matches every pyproject.toml in the workspace
lock-check:
	$(UV) lock --check

## hooks-check: the git hook regression battery (scripts/test-githooks.sh)
hooks-check:
	bash $(CURDIR)/scripts/test-githooks.sh

## audit: pip-audit over every locked dependency, runtime and dev
audit:
	@reqs=$$(mktemp); trap 'rm -f "$$reqs"' EXIT; \
	$(UV) export --frozen --all-packages --all-groups --no-hashes --no-emit-workspace --no-header > "$$reqs"; \
	grep -q '^[A-Za-z0-9]' "$$reqs" || { echo "uv export produced no requirements to audit" >&2; exit 1; }; \
	$(RUN) pip-audit --strict -r "$$reqs"
