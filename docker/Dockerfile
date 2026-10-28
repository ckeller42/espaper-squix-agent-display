# Build environment for the Squix 2.9" ESPaper Plus Kit (ESP8266 WROOM-02).
#
# Why linux/amd64 is pinned and not a build arg: the ESP8266 compiler
# (xtensa-lx106-elf-gcc) has never been built for arm64 -- neither the official
# PlatformIO package nor the pioarduino fork ships a darwin_arm64 or
# linux_arm64 binary. On Apple Silicon this image runs under emulation; on
# GitHub Actions' ubuntu runners it runs natively. Same image, same artifacts.
FROM --platform=linux/amd64 python:3.12-slim-bookworm

# Pinned so a rebuild six months from now produces the same compiler.
ARG PLATFORMIO_VERSION=6.2.0

ENV PLATFORMIO_CORE_DIR=/opt/pio \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install "platformio==${PLATFORMIO_VERSION}"

# Warm the package cache at image-build time. Copying only platformio.ini keeps
# this layer cached until the dependency set actually changes -- editing the
# sketch does not re-download a 100MB toolchain.
WORKDIR /project
COPY platformio.ini /project/platformio.ini
COPY pio /project/pio
# Only the 2.9" black/white environment. platformio.ini also defines 4.2", 7.5"
# and TTGO environments that pull the whole espressif32 platform -- installing
# those would roughly triple the image for hardware we do not own.
ARG PIO_ENV=Espaper29Bw-PROD
RUN pio pkg install -e "${PIO_ENV}"

# The container runs as the caller's UID (see scripts/dev.sh) so that files it
# writes into the bind-mounted source tree stay owned by the host user. That
# UID is not known at build time, so the shared PlatformIO dir must be writable
# by anyone. This is a disposable build image, not a multi-tenant host.
RUN chmod -R a+rwX /opt/pio

CMD ["pio", "run"]
