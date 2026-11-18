#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
docker compose config -q
bash backup-local.sh
docker compose build
docker compose stop web api worker
docker compose run --rm --no-deps -T api alembic upgrade head
docker compose up -d
