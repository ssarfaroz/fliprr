# One-time setup on Windows. Run in PowerShell from the fliprr folder:
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1
# Installs fliprr into .\.venv, then `fliprr setup` asks for your project folder,
# downloads the speech model, checks the Claude login, turns on autostart and starts it.
# Keep this file ASCII-only: Windows PowerShell 5.1 reads scripts as ANSI.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (Get-Command py -ErrorAction SilentlyContinue) { $python = "py"; $pyArgs = @("-3") }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $python = "python"; $pyArgs = @() }
else {
    Write-Host "Python not found. Install it, then close and reopen PowerShell and run this again:"
    Write-Host "  winget install -e --id Python.Python.3.12"
    exit 1
}

& $python @pyArgs -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Python 3.10 or newer is required:  winget install -e --id Python.Python.3.12"
    exit 1
}

& $python @pyArgs -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e .
if ($LASTEXITCODE -ne 0) { Write-Host "Installing packages failed (see the messages above)."; exit 1 }

# fliprr.bat runs fliprr commands from this folder, e.g.  .\fliprr.bat doctor
$bat = Join-Path $root "fliprr.bat"
Set-Content -Path $bat -Encoding ASCII -Value "@echo off`r`n`"%~dp0.venv\Scripts\python.exe`" -m fliprr %*`r`n"

& .\.venv\Scripts\python.exe -m fliprr setup
