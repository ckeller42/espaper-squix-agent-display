#!/usr/bin/env bash
# Local gate -- runs the same checks as .github/workflows/ci.yml.
# Run this before opening a PR; `main` is protected, so CI red means no merge.
#
#   ./scripts/gate.sh
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

fail=0
ran=()
skipped=()
step() { printf '\n==> %s\n' "$1"; }

step "secrets (detect-secrets via pre-commit)"
if command -v pre-commit >/dev/null 2>&1; then
    if pre-commit run --all-files; then ran+=("secrets"); else fail=1; fi
else
    skipped+=("secrets: pre-commit not found")
    echo "pre-commit not installed -- skipping (CI will still run it)" >&2
fi

step "server tests (unit, payload parity, fake-device protocol)"
# Optional tools are skipped with a message, not failed: the gate must stay
# runnable on a machine without them. CI installs all of them and runs every step.
if command -v uv >/dev/null 2>&1; then
    if (cd server && uv run --frozen pytest -q); then ran+=("server tests"); else fail=1; fi
else
    skipped+=("server tests: uv not found")
    echo "uv not installed -- skipping (CI will still run it)" >&2
fi

step "native firmware tests (real EspaperParser vs a live server)"
# -e is explicit on purpose: default_envs is the firmware env, and a
# bare `pio test` / `pio test -e <device env>` fails by design. The test binary execs server/.venv/bin/python.
if ! command -v pio >/dev/null 2>&1; then
    skipped+=("native tests: pio not found")
    echo "PlatformIO (pio) not installed -- skipping (CI will still run it)" >&2
elif ! command -v uv >/dev/null 2>&1; then
    skipped+=("native tests: uv not found")
    echo "uv not installed, cannot provision server/.venv -- skipping (CI will still run it)" >&2
else
    if uv sync --frozen --project server >/dev/null && pio test -e native; then
        ran+=("native tests")
    else
        fail=1
    fi
fi

step "firmware build (containerised, same image as CI)"
# Captured rather than streamed so the warning gate below can read it. The
# build is the slow part, so it runs once and both checks share the output.
have_build=0
if ! command -v docker >/dev/null 2>&1; then
    skipped+=("firmware build: docker not found")
    echo "docker not installed -- skipping build and warning gate (CI will still run them)" >&2
else
    # "ran" only ever lists checks that passed; any failure sets fail and the verdict ignores the count.
    if ./scripts/dev.sh build > build.log 2>&1; then
        ran+=("firmware build")
        have_build=1
        grep -E "RAM:|Flash:" build.log || true
    else
        tail -30 build.log
        fail=1
    fi
fi

step "warning gate"
# A warning-free build is part of "done" here. -Werror is not used because it
# would also fail on framework headers we do not control; this checks the
# build output we actually own.
if (( ! have_build )); then
    skipped+=("warning gate: no build output")
    echo "no build output to check -- skipped" >&2
else
    if grep -iE "warning" build.log; then
        echo "FAIL: build produced warnings (above). Fix them at the source." >&2
        fail=1
    else
        ran+=("warning gate")
        echo "build is warning-free"
    fi
fi

# The verdict names what ran. A skipped check is not a pass, and a run in which
# nothing could execute is inconclusive, never green.
join() { local IFS=,; echo "$*"; }
n_ran=${#ran[@]}
n_skip=${#skipped[@]}
total=$((n_ran + n_skip))
if (( fail )); then
    printf '\n*** GATE FAILED ***\n' >&2
    exit 1
elif (( n_ran == 0 )); then
    printf '\n*** GATE INCONCLUSIVE -- no checks could run (%s) ***\n' "$(join "${skipped[@]}")" >&2
    exit 2
elif (( n_skip )); then
    printf '\n*** GATE PASSED (%d of %d checks; skipped: %s) ***\n' "$n_ran" "$total" "$(join "${skipped[@]}")"
else
    printf '\n*** GATE PASSED (%d of %d checks) ***\n' "$n_ran" "$total"
fi
