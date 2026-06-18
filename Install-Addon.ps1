# Install-Addon.ps1
# Copies FreeCAD AI Copilot addon files into %APPDATA%\FreeCAD\v1-1\Mod\FreeCADCopilot\
# After running, restart FreeCAD - the AI Copilot panel loads automatically.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$source = Join-Path $PSScriptRoot "freecad-addon\FreeCADCopilot"
$dest   = Join-Path $env:APPDATA  "FreeCAD\v1-1\Mod\FreeCADCopilot"

if (-not (Test-Path $source)) {
    Write-Error "Source directory not found: $source"
    exit 1
}

if (-not (Test-Path $dest)) {
    New-Item -ItemType Directory -Path $dest | Out-Null
    Write-Host "Created: $dest"
} else {
    Write-Host "Updating: $dest"
}

$files = @("InitGui.py", "copilot_panel.py", "agent_core.py", "system_prompt.py")

foreach ($file in $files) {
    $src = Join-Path $source $file
    $tgt = Join-Path $dest   $file

    if (-not (Test-Path $src)) {
        Write-Warning "Missing source file: $src -- skipping"
        continue
    }

    Copy-Item -Path $src -Destination $tgt -Force
    Write-Host "  Copied: $file"
}

$freecadPython = @(
    "$env:LOCALAPPDATA\Programs\FreeCAD 1.1\bin\python.exe",
    "$env:ProgramFiles\FreeCAD 1.1\bin\python.exe",
    "$env:ProgramFiles\FreeCAD\bin\python.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($freecadPython) {
    $hasOpenAI = & $freecadPython -c "import openai; print('ok')" 2>$null
    if ($hasOpenAI -ne "ok") {
        Write-Host ""
        Write-Host "[!] openai not found in FreeCAD Python." -ForegroundColor Yellow
        Write-Host "    In FreeCAD Python console, run:" -ForegroundColor Yellow
        Write-Host "    import subprocess, sys; subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'openai'])" -ForegroundColor Cyan
    } else {
        Write-Host "  openai package: OK"
    }
} else {
    Write-Host "[!] FreeCAD python.exe not found - install openai manually via FreeCAD Python console." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Done. Restart FreeCAD - AI Copilot panel will appear on the right." -ForegroundColor Green