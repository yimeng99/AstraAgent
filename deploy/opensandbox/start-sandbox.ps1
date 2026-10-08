$ErrorActionPreference = 'Stop'
docker compose -f (Join-Path $PSScriptRoot 'compose.yaml') up -d --build --wait
if ($LASTEXITCODE -ne 0) { throw 'OpenSandbox Docker 启动失败，请查看 compose logs server' }
