[CmdletBinding()]
param(
    [string]$PythonCommand = "py",
    [string]$PythonVersion = "3.14"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$requirements = Join-Path $projectRoot "requirements-resolve.txt"
$target = Join-Path $projectRoot ".resolve_deps"

& $PythonCommand "-$PythonVersion" -m pip install `
    --requirement $requirements `
    --target $target `
    --upgrade

if ($LASTEXITCODE -ne 0) {
    throw "Resolve dependency installation failed with exit code $LASTEXITCODE"
}

Write-Host "Installed Resolve runtime dependencies:"
Write-Host "  $target"
