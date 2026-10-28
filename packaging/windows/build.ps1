# Builds dist\sudo-make-music-portable.exe  (run on Windows, Python 3.12 recommended)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\..")
python -m pip install --upgrade pip pyinstaller
python -m pip install ".[windows]"
python -m PyInstaller --noconfirm --distpath dist --workpath build\pyinstaller packaging\windows\sudo-make-music.spec
Write-Host "built dist\sudo-make-music-portable.exe"
