#!/usr/bin/env bash
# Local gate -- runs the same checks as .github/workflows/ci.yml.
# Run this before opening a PR; `main` is protected, so CI red means no merge.
#
#   ./scripts/gate.sh
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

fail=0
step() { printf '\n==> %s\n' "$1"; }

step "secrets (detect-secrets via pre-commit)"
if command -v pre-commit >/dev/null 2>&1; then
    pre-commit run --all-files || fail=1
else
    echo "pre-commit not installed -- skipping (CI will still run it)" >&2
fi

step "server tests (unit, payload parity, fake-device protocol)"
# Optional tools are skipped with a message, not failed: the gate must stay
# runnable on a machine without them. CI installs all of them and runs every step.
if command -v uv >/dev/null 2>&1; then
    (cd server && uv run --frozen pytest -q) || fail=1
else
    echo "uv not installed -- skipping (CI will still run it)" >&2
fi

step "native firmware tests (real EspaperParser vs a live server)"
# -e is explicit on purpose: default_envs is native, and `pio test -e <device
# env>` fails by design. The test binary execs server/.venv/bin/python.
if ! command -v pio >/dev/null 2>&1; then
    echo "PlatformIO (pio) not installed -- skipping (CI will still run it)" >&2
elif ! command -v uv >/dev/null 2>&1; then
    echo "uv not installed, cannot provision server/.venv -- skipping (CI will still run it)" >&2
else
    uv sync --frozen --project server >/dev/null && pio test -e native || fail=1
fi

step "firmware build (containerised, same image as CI)"
# Captured rather than streamed so the warning gate below can read it. The
# build is the slow part, so it runs once and both checks share the output.
have_build=0
if ! command -v docker >/dev/null 2>&1; then
    echo "docker not installed -- skipping build and warning gate (CI will still run them)" >&2
elif ./scripts/dev.sh build > build.log 2>&1; then
    have_build=1
    grep -E "RAM:|Flash:" build.log || true
else
    tail -30 build.log
    fail=1
fi

step "warning gate"
# A warning-free build is part of "done" here. -Werror is not used because it
# would also fail on framework headers we do not control; this checks the
# build output we actually own.
if (( ! have_build )); then
    echo "no build output to check -- skipped" >&2
elif grep -iE "warning" build.log; then
    echo "FAIL: build produced warnings (above). Fix them at the source." >&2
    fail=1
else
    echo "build is warning-free"
fi

if (( fail )); then
    printf '\n*** GATE FAILED ***\n' >&2
    exit 1
fi
printf '\n*** GATE PASSED ***\n'
