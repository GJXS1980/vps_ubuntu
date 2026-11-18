#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
umask 077
docker compose version
docker info >/dev/null
mkdir -p data backups secrets/{web,agents}
[[ -e .env ]] || cp .env.example .env
docker compose build
docker compose run --rm --no-deps -v "$PWD/secrets/web:/tls" -v "$PWD/scripts:/scripts:ro" api sh /scripts/setup-tls.sh
docker compose run --rm --no-deps api alembic upgrade head
docker compose run --rm --no-deps api python -m app.maintenance bootstrap
docker compose up -d
docker compose run --rm --no-deps -T -v "$PWD/secrets/web:/tls:ro" -v "$PWD/scripts:/scripts:ro" api python /scripts/check-web.py
echo '入口见 .env 的 PORTAL_ORIGIN；首次使用请配置管理隧道和 VPS。'
