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

step "firmware build (containerised, same image as CI)"
# Captured rather than streamed so the warning gate below can read it. The
# build is the slow part, so it runs once and both checks share the output.
if ./scripts/dev.sh build > build.log 2>&1; then
    grep -E "RAM:|Flash:" build.log || true
else
    tail -30 build.log
    fail=1
fi

step "warning gate"
# A warning-free build is part of "done" here. -Werror is not used because it
# would also fail on framework headers we do not control; this checks the
# build output we actually own.
if grep -iE "warning" build.log; then
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
