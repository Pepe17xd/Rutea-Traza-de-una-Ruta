$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$secretPath = Join-Path $root 'include/secrets.wifi.h'
$iniPath = Join-Path $root 'platformio.ini'
$caPath = Join-Path $root 'include/amazon_root_ca1.h'

function Report([string]$name, [bool]$ok) {
    if ($ok) { Write-Host "PASS $name" -ForegroundColor Green }
    else { Write-Host "FAIL $name" -ForegroundColor Red }
}

$secretExists = Test-Path -LiteralPath $secretPath
$secret = if ($secretExists) { [IO.File]::ReadAllText($secretPath) } else { '' }
$tokenMatch = [regex]::Match($secret, '(?m)^\s*#\s*define\s+RUTEA_DEVICE_TOKEN\s+"([^"]*)"')
$tokenValue = $tokenMatch.Groups[1].Value
$tokenOk = $tokenMatch.Success -and $tokenValue.Trim().Length -ge 24 -and
    $tokenValue -notmatch '(?i)placeholder|your[_ -]?token|changeme|replace|example|dummy|token[_ -]?here'
$urlOk = $secret -match '(?m)^\s*#\s*define\s+RUTEA_API_BASE_URL\s+"https://0wj6cqa8yi\.execute-api\.us-east-1\.amazonaws\.com/api/v1"\s*$'
$caOk = $secret -match '(?m)^\s*#\s*define\s+RUTEA_TLS_CA_CERT\s+AMAZON_ROOT_CA1_PEM\s*$' -and
    (Test-Path -LiteralPath $caPath) -and
    ([IO.File]::ReadAllText($caPath) -match 'Amazon Root CA 1')
$baseOk = $secret -match '(?m)^\s*#\s*define\s+RUTEA_SEQUENCE_BASE\s+0ULL\s*$' -and
    $secret -match '(?m)^\s*#\s*define\s+RUTEA_SEQUENCE_BASE_CONFIGURED\s+1\s*$'
$ignored = $false
git -C (Split-Path -Parent (Split-Path -Parent $root)) check-ignore -q $secretPath
$ignored = ($LASTEXITCODE -eq 0)
$ini = [IO.File]::ReadAllText($iniPath)
$telemetryOff = $ini -match '(?m)^\s*build_flags\s*=\s*-D RUTEA_ENABLE_TELEMETRY=0\s*$'

Report 'Local device token present and non-placeholder (value withheld)' $tokenOk
Report 'Local secrets file ignored by Git' $ignored
Report 'Confirmed HTTPS API base URL configured' $urlOk
Report 'Amazon Root CA 1 configured for strict TLS' $caOk
Report 'Explicit sequence base 0 configured' $baseOk
Report 'Telemetry publishing disabled by default' $telemetryOff

if (-not ($tokenOk -and $ignored -and $urlOk -and $caOk -and $baseOk -and $telemetryOff)) { exit 1 }
