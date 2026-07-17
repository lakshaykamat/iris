#!/usr/bin/env bash
# Run this script directly on the VPS to set up and start iris end-to-end.
# Always pulls the latest image and restarts the container.
set -euo pipefail

IMAGE="${IMAGE:-lakshaykamat/iris:latest}"
CONTAINER="${CONTAINER:-iris}"
DATA_DIR="${DATA_DIR:-$(pwd)/data}"
ENV_FILE="${ENV_FILE:-.env}"

# ── colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[ok]${NC}  $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*"; }
die()  { echo -e "${RED}[fail]${NC} $*" >&2; exit 1; }

echo "==> iris setup — $(date)"

# ── 1. prerequisites ─────────────────────────────────────────────────────────
echo
echo "--- Checking prerequisites"

command -v docker &>/dev/null || die "docker is not installed. Install it first: https://docs.docker.com/engine/install/"
ok "docker $(docker --version | awk '{print $3}' | tr -d ',')"

docker info &>/dev/null || die "docker daemon is not running (try: sudo systemctl start docker)"
ok "docker daemon is up"

# ── 2. .env validation ───────────────────────────────────────────────────────
echo
echo "--- Validating .env"

[[ -f "$ENV_FILE" ]] || die ".env not found at $(pwd)/$ENV_FILE — create it before running this script."
ok ".env found"

check_var() {
  local name="$1" required="${2:-true}"
  local val
  val=$(grep -E "^${name}=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'")
  if [[ -z "$val" ]]; then
    [[ "$required" == "true" ]] && die "Missing required variable in .env: $name" || warn "$name not set (optional)"
  else
    ok "$name is set"
  fi
}

check_var TELEGRAM_TOKEN
check_var OWNER_CHAT_ID
check_var OPENAI_API_KEY
check_var OWNER_TZ false
check_var GIF_API_KEY false

# ── 3. data directory ────────────────────────────────────────────────────────
echo
echo "--- Setting up data directory"

mkdir -p "$DATA_DIR"
ok "data dir: $DATA_DIR"

# ── 4. pull image ─────────────────────────────────────────────────────────────
echo
echo "--- Image"

echo "    Pulling $IMAGE ..."
docker pull "$IMAGE"
ok "pulled $IMAGE"

# ── 5. replace running container ─────────────────────────────────────────────
echo
echo "--- Container"

if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
  echo "    Stopping existing container '$CONTAINER' ..."
  docker rm -f "$CONTAINER" &>/dev/null
fi

docker run -d \
  --name "$CONTAINER" \
  --restart unless-stopped \
  --env-file "$ENV_FILE" \
  -p 5050:5050 \
  -v "${DATA_DIR}:/app/data" \
  "$IMAGE"

ok "container '$CONTAINER' started"

# ── 6. health check ───────────────────────────────────────────────────────────
echo
echo "--- Health check (waiting 5s)"
sleep 5

STATUS=$(docker inspect --format '{{.State.Status}}' "$CONTAINER" 2>/dev/null || echo "missing")

if [[ "$STATUS" == "running" ]]; then
  ok "container is running"
else
  die "container status is '$STATUS' — check logs: docker logs $CONTAINER"
fi

# ── 7. summary ───────────────────────────────────────────────────────────────
echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  iris is running"
echo "  Image:     $IMAGE"
echo "  Data:      $DATA_DIR"
echo "  Dashboard: http://$(curl -sf https://ipinfo.io/ip 2>/dev/null || echo 'localhost'):5050"
echo "  Logs:      docker logs -f $CONTAINER"
echo "  Stop:      docker rm -f $CONTAINER"
echo "  Update:    ./scripts/start-vps.sh  (always pulls latest)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
