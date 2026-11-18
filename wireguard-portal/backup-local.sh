#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
name="portal-$(date -u +%Y%m%dT%H%M%SZ)-$$.enc"
docker compose run --rm --no-deps -T api python -m app.maintenance backup "/backups/$name"
echo "backups/$name"
