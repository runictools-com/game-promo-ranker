#!/usr/bin/env bash
set -euo pipefail

root=/home/deploy/steam-sale-ranker
cd "$root"
exec 9>/tmp/gamepromo-refresh.lock
if ! flock -n 9; then
  echo "[daily] another GamePromo refresh is already running"
  exit 0
fi

expected=$(git rev-parse HEAD)
image_revision=$(docker image inspect steam-gen:latest --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' 2>/dev/null || true)
if [[ "$image_revision" != "$expected" ]]; then
  echo "[daily] rebuilding steam-gen:latest for $expected (found ${image_revision:-missing})"
  docker build -f Dockerfile.gen --build-arg "VCS_REF=$expected" -t steam-gen:latest .
fi

refresh_status=0
docker run --rm --entrypoint python -v steam_data:/app/data steam-gen:latest \
  refresh_daily.py --pages 20 --data-dir data || refresh_status=$?

contract_status=0
docker run --rm --entrypoint python -v steam_data:/app/data steam-gen:latest \
  verify_release.py --root /app --data-dir /app/data --require-fresh || contract_status=$?

if [[ "$contract_status" -ne 0 ]]; then
  echo "[daily] release contract failed"
  exit "$contract_status"
fi
exit "$refresh_status"
