# Install fliprr on Windows into .\.venv and create fliprr.bat.
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1 [-Autostart]
param([switch]$Autostart)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (Get-Command py -ErrorAction SilentlyContinue) { $python = "py"; $pyArgs = @("-3") }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $python = "python"; $pyArgs = @() }
else { throw "Python 3.10+ not found. Install it from https://www.python.org/downloads/ (check 'Add to PATH')." }

& $python @pyArgs -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 'Python 3.10+ is required')"
if ($LASTEXITCODE -ne 0) { throw "Python 3.10+ is required" }

& $python @pyArgs -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e .
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

$bat = Join-Path $root "fliprr.bat"
Set-Content -Path $bat -Encoding ASCII -Value "@echo off`r`n`"%~dp0.venv\Scripts\fliprr.exe`" %*`r`n"

if ($Autostart) {
    $startup = [Environment]::GetFolderPath("Startup")
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut((Join-Path $startup "fliprr.lnk"))
    $link.TargetPath = $bat
    $link.WorkingDirectory = $env:USERPROFILE
    $link.WindowStyle = 7  # minimized console window
    $link.Save()
    Write-Host "Autostart: shortcut added to $startup"
}

Write-Host ""
Write-Host "Done. Next:"
Write-Host "  $bat init      # create the settings file, put your project folder there"
Write-Host "  $bat doctor    # check everything"
Write-Host "  $bat test-mic  # test the microphone from across the room"
Write-Host "  $bat           # start"
