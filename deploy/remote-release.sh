#!/usr/bin/env bash
set -euo pipefail
expected="$1"
[[ "$expected" =~ ^[0-9a-f]{40}$ ]]
cd /home/deploy/steam-sale-ranker
exec 9>/tmp/gamepromo-release.lock
flock -n 9
git diff --quiet
git diff --cached --quiet
git fetch origin main
test "$(git rev-parse origin/main)" = "$expected"
previous=$(git rev-parse HEAD)
git merge --ff-only "$expected"
docker tag steam-sale-app:latest "steam-sale-app:rollback-$previous"
docker tag steam-gen:latest "steam-gen:rollback-$previous"
docker compose -f docker-compose.prod.yml build --build-arg "VCS_REF=$expected" gamepromo
docker build -f Dockerfile.gen --build-arg "VCS_REF=$expected" -t steam-gen:latest .
test "$(git rev-parse HEAD)" = "$expected"
docker compose -f docker-compose.prod.yml up -d --no-build gamepromo
python3 deploy/install_cron.py
refresh_status=0
flock -n /tmp/gamepromo-refresh.lock timeout 9000 docker run --rm --entrypoint python -v steam_data:/app/data steam-gen:latest refresh_daily.py --pages 20 || refresh_status=$?
docker inspect gamepromo --format '{{.State.Health.Status}}'
docker inspect gamepromo --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'
docker logs --tail 12 gamepromo
curl -fsS https://gamepromo.runictools.com/healthz
echo "release=$expected rollback=$previous"
exit "$refresh_status"
