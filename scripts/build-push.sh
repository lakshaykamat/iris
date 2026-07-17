#!/usr/bin/env bash
set -euo pipefail

# ── config ────────────────────────────────────────────────────────────────────
IMAGE="${IMAGE:-lakshaykamat/iris}"
TAG="${TAG:-latest}"
PLATFORM="${PLATFORM:-linux/amd64}"       # match your VPS arch
# ─────────────────────────────────────────────────────────────────────────────

FULL="${IMAGE}:${TAG}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Building ${FULL} (${PLATFORM})"
docker buildx build \
  --platform "${PLATFORM}" \
  --tag "${FULL}" \
  --load \
  "${ROOT}"

echo "==> Pushing ${FULL}"
docker push "${FULL}"

echo "==> Done: ${FULL}"
