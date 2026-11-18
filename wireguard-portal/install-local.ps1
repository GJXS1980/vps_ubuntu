$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
function Run-Docker { & docker @args; if ($LASTEXITCODE -ne 0) { throw "Docker 执行失败" } }
Run-Docker compose version
Run-Docker info | Out-Null
'data','backups','secrets/web','secrets/agents' | ForEach-Object { New-Item -ItemType Directory -Force $_ | Out-Null }
if (!(Test-Path .env)) { Copy-Item .env.example .env }
Run-Docker compose build
Run-Docker compose run --rm --no-deps -v "${PSScriptRoot}/secrets/web:/tls" -v "${PSScriptRoot}/scripts:/scripts:ro" api sh /scripts/setup-tls.sh
Run-Docker compose run --rm --no-deps api alembic upgrade head
Run-Docker compose run --rm --no-deps api python -m app.maintenance bootstrap
Run-Docker compose up -d
Run-Docker compose run --rm --no-deps -T -v "${PSScriptRoot}/secrets/web:/tls:ro" -v "${PSScriptRoot}/scripts:/scripts:ro" api python /scripts/check-web.py
Write-Host '访问 .env 中的 PORTAL_ORIGIN，核对 secrets/web/tls.crt 并检查 /api/health。'
