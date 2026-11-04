# Compatibility wrapper; the root Node orchestrator owns all deploy validation.
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Write-Host "Usa npm run academy:check desde la raiz Linux para revisar credenciales, cuenta AWS y permisos reales."
Push-Location $root
try {
  & npm.cmd run academy:check -- --dry-run
  exit $LASTEXITCODE
} finally { Pop-Location }
