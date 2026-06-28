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

# ponytail: vfs full-copies every layer (no overlay) so --layers blows the disk
# fast. Without it + post-build prune the volume stays bounded to ~final image
# size. KEEP_CACHE=1 retains intermediates for incremental rebuilds (grows fast
# — purge with `docker volume rm aipc-buildah-storage`).
PRUNE_CMD='buildah --storage-driver vfs rmi --prune --force || true'
[ -n "${KEEP_CACHE:-}" ] && PRUNE_CMD=': skip prune (KEEP_CACHE set)'

TAG_ARGS=$(for t in ${TAGS}; do printf -- '-t aipc:%s ' "$t"; done)

echo "==> Step 2/2: build image (in buildah container, privileged)"
docker run --rm --privileged \
  -v "${REPO_ROOT}:/build" \
  -v "aipc-buildah-storage:/var/lib/containers" \
  quay.io/buildah/stable \
  sh -euc "
    buildah --storage-driver vfs build \
      --format oci \
      ${TAG_ARGS} \
      -f targets/bootc/Containerfile \
      /build
    ${PRUNE_CMD}
  "

echo ""
echo "==> Build complete. Tags:"
for t in ${TAGS}; do
  echo "  aipc:${t}"
done

vol_size=$(docker system df -v 2>/dev/null | awk '/aipc-buildah-storage/ {print $3}')
[ -n "${vol_size}" ] && echo "==> buildah volume size: ${vol_size}"

echo ""
echo "To push to ghcr.io:"
echo "  docker run --rm -v aipc-buildah-storage:/var/lib/containers quay.io/buildah/stable \\"
echo "    buildah --storage-driver vfs push --creds <user>:<token> aipc:rolling docker://ghcr.io/a9650615/aipc:rolling"
