#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
name=${1:?传入 backups 目录内的备份文件名}
[[ "$name" =~ ^[a-zA-Z0-9._-]+\.enc$ && -f "backups/$name" ]]
read -rp '恢复会替换平台数据。输入 RESTORE 继续: ' confirm
[[ "$confirm" == RESTORE ]]
docker compose stop web api worker
bash backup-local.sh
docker compose run --rm --no-deps -T api python -m app.maintenance restore "/backups/$name"
docker compose run --rm --no-deps -T api alembic upgrade head
docker compose up -d
