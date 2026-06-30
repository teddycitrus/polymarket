# Launcher for the nightly forecasting run, intended for Task Scheduler.
# Loads variables from the project .env (the Python scripts read os.environ
# directly and do not parse .env themselves), then runs scripts/nightly.py.
#
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\run-nightly.ps1 [-Limit 10]

param(
    [int]$Limit = 10
)

$ErrorActionPreference = "Stop"

# Project root is the parent of this script's folder.
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# Load .env into the process environment.
$envFile = Join-Path $Root ".env"
if (Test-Path $envFile) {
    foreach ($line in Get-Content $envFile) {
        $trimmed = $line.Trim()
        if ($trimmed -eq "" -or $trimmed.StartsWith("#")) { continue }
        $idx = $trimmed.IndexOf("=")
        if ($idx -lt 1) { continue }
        $name = $trimmed.Substring(0, $idx).Trim()
        $value = $trimmed.Substring($idx + 1).Trim().Trim('"').Trim("'")
        Set-Item -Path "Env:$name" -Value $value
    }
}

& "C:\Python314\python.exe" (Join-Path $Root "scripts\nightly.py") --limit $Limit
exit $LASTEXITCODE
