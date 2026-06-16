[CmdletBinding()]
param(
    [string]$ResolveScriptsRoot = (
        Join-Path $env:APPDATA "Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts"
    )
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$source = (Resolve-Path $PSScriptRoot).Path
$databasePath = Join-Path $projectRoot "timer_db.yaml"
$exampleDatabasePath = Join-Path $projectRoot "examples\timer_db.yaml"
$resolveDependencies = Join-Path $projectRoot ".resolve_deps"
$utilityRoot = Join-Path $ResolveScriptsRoot "Utility"
$destination = Join-Path $utilityRoot "Resolve Timer"

if (-not (Test-Path -LiteralPath (Join-Path $resolveDependencies "yaml"))) {
    throw "Resolve dependencies are missing. Run .\scripts\Install-ResolveDependencies.ps1 first."
}

if (-not (Test-Path -LiteralPath $databasePath)) {
    Copy-Item -LiteralPath $exampleDatabasePath -Destination $databasePath
    Write-Host "Initialized database: $databasePath"
}

New-Item -ItemType Directory -Path $utilityRoot -Force | Out-Null

if (Test-Path -LiteralPath $destination) {
    $existing = Get-Item -LiteralPath $destination -Force
    $existingTarget = @($existing.Target)[0]
    if ($existing.LinkType -eq "Junction" -and $existingTarget -eq $source) {
        # Resolve executes scripts from junctions without defining __file__.
        Remove-Item -LiteralPath $destination
        Write-Host "Removed the previous junction deployment."
    }
    elseif ($existing.LinkType) {
        throw "Destination is an unexpected link and was not changed: $destination"
    }
}

New-Item -ItemType Directory -Path $destination -Force | Out-Null

foreach ($scriptName in @(
    "ResolveFusionProbe.py",
    "ResolveProbe.py",
    "ResolveRuntime.py",
    "ResolveTimer.py",
    "ResolveUILayoutProbe.py",
    "ResolveUIProbe.py"
)) {
    $sourceScript = Join-Path $source $scriptName
    $launcherPath = Join-Path $destination $scriptName
    $sourceLiteral = ConvertTo-Json $sourceScript -Compress
    $resolveDependenciesLiteral = ConvertTo-Json $resolveDependencies -Compress
    $launcher = @"
"""Generated Resolve launcher. Rerun Install-ResolveScripts.ps1 to update."""
import runpy
import sys

resolve_dependencies = $resolveDependenciesLiteral
if resolve_dependencies not in sys.path:
    sys.path.insert(0, resolve_dependencies)

runpy.run_path(
    $sourceLiteral,
    init_globals={
        "resolve": globals().get("resolve"),
        "fusion": globals().get("fusion"),
        "bmd": globals().get("bmd"),
    },
    run_name="__main__",
)
"@
    Set-Content -LiteralPath $launcherPath -Value $launcher -Encoding utf8
}

Write-Host "Installed Resolve Timer launchers:"
Write-Host "  $destination"
Write-Host "  Source checkout: $projectRoot"
Write-Host ""
Write-Host "Restart Resolve, then find Resolve Timer under Workspace > Scripts."
Write-Host "Run ResolveProbe for source-marker diagnostics."
Write-Host "Run ResolveFusionProbe with one Media Pool clip selected and the"
Write-Host "timeline playhead over the matching video item."
