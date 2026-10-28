#!/usr/bin/env bash
# Thin wrapper around the containerised PlatformIO build.
#
#   ./scripts/dev.sh build     compile
#   ./scripts/dev.sh clean     remove build artifacts
#   ./scripts/dev.sh shell     interactive shell in the build image
#   ./scripts/dev.sh size      report flash/RAM usage
set -euo pipefail

IMAGE="squix-espaper-build:latest"
# Our hardware: 2.9" black/white ESPaper. Override with SQUIX_ENV.
PIO_ENV="${SQUIX_ENV:-Espaper29Bw-PROD}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKER_HOST_REMOTE="${SQUIX_DOCKER_HOST:-}"

docker_cmd() {
    if [[ -n "$DOCKER_HOST_REMOTE" ]]; then
        DOCKER_HOST="$DOCKER_HOST_REMOTE" docker "$@"
    else
        docker "$@"
    fi
}

ensure_image() {
    if ! docker_cmd image inspect "$IMAGE" >/dev/null 2>&1; then
        echo "==> building $IMAGE (first run pulls the toolchain, ~5 min)"
        docker_cmd build --platform linux/amd64 \
            -t "$IMAGE" -f "$PROJECT_ROOT/docker/Dockerfile" "$PROJECT_ROOT"
    fi
}

run_in_container() {
    # -it only when there really is a terminal, otherwise docker refuses with
    # "cannot attach stdin to a TTY-enabled container" under CI and agents.
    # macOS ships bash 3.2, where "${arr[@]}" on an EMPTY array trips
    # `set -u`. The ${arr[@]+...} guard expands to nothing in that case.
    local tty_flags=()
    [[ -t 0 && -t 1 ]] && tty_flags=(-it)

    docker_cmd run --rm ${tty_flags[@]+"${tty_flags[@]}"} \
        --platform linux/amd64 \
        -v "$PROJECT_ROOT:/project" \
        -u "$(id -u):$(id -g)" \
        -w /project \
        "$IMAGE" "$@"
}

ensure_image
case "${1:-build}" in
    build) run_in_container pio run -e "$PIO_ENV" ;;
    clean) run_in_container pio run -e "$PIO_ENV" -t clean ;;
    size)  run_in_container pio run -e "$PIO_ENV" -t size ;;
    shell) run_in_container bash ;;
    *)     echo "usage: $0 {build|clean|size|shell}" >&2; exit 2 ;;
esac
