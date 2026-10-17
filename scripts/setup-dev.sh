#!/usr/bin/env bash
# One-command developer setup, adapted from SceneForge's. Idempotent; `--check` verifies
# without changing anything and exits non-zero when something is missing, so it doubles as the
# "is this checkout set up" probe.
#   - points git at the tracked hooks in .githooks (commit-msg, pre-push)
#   - creates .venv from uv.lock with the dev group and both workspace packages (uv fetches
#     Python 3.12 if needed)
# Usage: scripts/setup-dev.sh [--check]
set -euo pipefail

check_only=0
case "${1:-}" in
  --check) check_only=1 ;;
  "") ;;
  *) echo "usage: scripts/setup-dev.sh [--check]" >&2; exit 2 ;;
esac

root="$(git rev-parse --show-toplevel)"
cd "$root"
status=0

note() { echo "ok      $*"; }
missing() { echo "MISSING $*"; status=1; }

# 1. uv is the declared package manager (pyproject.toml, uv.lock).
if command -v uv >/dev/null 2>&1; then
  note "uv $(uv --version | awk '{print $2}')"
else
  missing "uv; install it from https://docs.astral.sh/uv/getting-started/installation/ and re-run"
  exit $status
fi

# 2. Tracked git hooks.
want_hooks=".githooks"
have_hooks="$(git config --local --get core.hooksPath || true)"
if [ "$have_hooks" = "$want_hooks" ]; then
  note "core.hooksPath=$want_hooks"
elif [ "$check_only" = 1 ]; then
  missing "core.hooksPath=$want_hooks (have '${have_hooks:-unset}'); run scripts/setup-dev.sh"
else
  git config --local core.hooksPath "$want_hooks"
  echo "set     core.hooksPath=$want_hooks"
fi
for hook in commit-msg pre-push; do
  if [ -x "$want_hooks/$hook" ]; then
    note "hook $hook executable"
  else
    missing "hook $want_hooks/$hook is not executable (git tracks the mode; check the checkout)"
  fi
done

# 3. The workspace environment from the lockfile. `uv sync --check` also catches a venv that
#    exists but no longer matches the lock.
if [ "$check_only" = 1 ]; then
  if [ -x .venv/bin/python ]; then
    note ".venv ($(.venv/bin/python --version 2>&1))"
    if uv sync --locked --group dev --check >/dev/null 2>&1; then
      note ".venv matches uv.lock"
    else
      missing ".venv is out of date with uv.lock; run scripts/setup-dev.sh"
    fi
  else
    missing ".venv; run scripts/setup-dev.sh"
  fi
  if uv lock --check >/dev/null 2>&1; then
    note "uv.lock matches every pyproject.toml"
  else
    missing "uv.lock is stale; run: uv lock"
  fi
  for tool in ruff mypy pytest; do
    if [ -x ".venv/bin/$tool" ]; then note ".venv/bin/$tool"; else missing ".venv/bin/$tool; run scripts/setup-dev.sh"; fi
  done
else
  uv sync --locked --group dev
  echo "synced  .venv from uv.lock ($(.venv/bin/python --version 2>&1))"
fi
if [ "$(cat .python-version)" != "3.12" ]; then
  missing ".python-version must read 3.12 (CI and mypy pin the same)"
fi

if [ "$status" = 0 ]; then
  echo "scene-verify development tooling is installed."
else
  echo "scene-verify development tooling is incomplete; see the MISSING lines above." >&2
fi
exit $status
