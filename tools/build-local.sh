#!/bin/sh
# build-local.sh — build the aipc bootc image entirely in containers
# Requires: docker (via OrbStack on Mac), nothing else on host
set -eu

fail() { printf '%s\n' "$1" >&2; exit 1; }

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_DATE="$(date -u +%Y-%m-%d)"
IMAGE_REF="${IMAGE_REF:-ghcr.io/a9650615/aipc:${BUILD_DATE}}"
TAGS="${TAGS:-rolling ${BUILD_DATE}}"

docker info >/dev/null 2>&1 || fail "docker not available — start OrbStack"

echo "==> Step 1/2: render Containerfile (in python:3.12 container)"
docker run --rm \
  -v "${REPO_ROOT}:/repo" \
  -w /repo \
  python:3.12-slim \
  sh -c "pip install -q -e tools && aipc render bootc --image-ref '${IMAGE_REF}' --build-date '${BUILD_DATE}' --out targets/bootc/Containerfile"

[ -f "${REPO_ROOT}/targets/bootc/Containerfile" ] || fail "render failed — Containerfile not generated"

echo "==> Step 2/2: build image (in buildah container, privileged)"
docker run --rm --privileged \
  -v "${REPO_ROOT}:/build" \
  -v "aipc-buildah-storage:/var/lib/containers" \
  quay.io/buildah/stable \
  buildah build \
    --layers \
    --format oci \
    $(for t in ${TAGS}; do printf -- '-t aipc:%s ' "$t"; done) \
    -f targets/bootc/Containerfile \
    /build

echo ""
echo "==> Build complete. Tags:"
for t in ${TAGS}; do
  echo "  aipc:${t}"
done
echo ""
echo "To push to ghcr.io:"
echo "  docker run --rm -v aipc-buildah-storage:/var/lib/containers quay.io/buildah/stable \\"
echo "    buildah push --creds <user>:<token> aipc:rolling docker://ghcr.io/a9650615/aipc:rolling"
