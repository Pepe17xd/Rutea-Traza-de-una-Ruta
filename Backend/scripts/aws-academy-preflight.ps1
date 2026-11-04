# Compatibility wrapper. Real AWS Academy preflight/deploy must run from Ubuntu.
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Write-Host "Windows solo ejecuta la validacion local. El preflight AWS requiere Ubuntu y credenciales temporales activas."
Push-Location $root
try {
  & npm.cmd run academy:check -- --dry-run
  exit $LASTEXITCODE
} finally { Pop-Location }
