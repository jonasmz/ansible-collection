#!/bin/sh
# Build the Koha test image once: ./build.sh [koha-release]
set -eu
release="${1:-26.05}"
cd "$(dirname "$0")"
exec podman build --build-arg "KOHA_RELEASE=$release" -t "localhost/koha-molecule:$release" -f Containerfile .
