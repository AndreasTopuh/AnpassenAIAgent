# Setup script for Windows — creates junctions into ~/.hermes/hooks/
# Usage: .\hooks\setup.ps1

$ErrorActionPreference = "Stop"

$RepoDir = (Resolve-Path "$PSScriptRoot\..").Path
$HooksTarget = "$env:USERPROFILE\.hermes\hooks"

Write-Host "Setting up Hermes hooks from $RepoDir\hooks\"

if (-not (Test-Path $HooksTarget)) {
    New-Item -Path $HooksTarget -ItemType Directory -Force | Out-Null
}

Get-ChildItem -Path "$RepoDir\hooks" -Directory | ForEach-Object {
    $name = $_.Name
    $link = Join-Path $HooksTarget $name
    $source = $_.FullName

    if (Test-Path $link) {
        $item = Get-Item $link -Force
        if ($item.LinkType) {
            Remove-Item $link -Force
        } else {
            Write-Host "  ! $link already exists and is not a junction — skipping"
            return
        }
    }

    cmd /c "mklink /J `"$link`" `"$source`"" | Out-Null
    Write-Host "  Linked $name -> $source"
}

Write-Host ""
Write-Host "Done. Restart Hermes gateway for hooks to take effect."
