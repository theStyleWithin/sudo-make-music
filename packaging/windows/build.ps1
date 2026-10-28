# Builds dist\sudo-make-music-portable.exe  (run on Windows, Python 3.12 recommended)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\..")
python -m pip install --upgrade pip pyinstaller
python -m pip install .
python -m PyInstaller --noconfirm --onefile --name sudo-make-music-portable `
  --collect-all pip --collect-all sudo_make_music `
  --distpath dist --workpath build\pyinstaller packaging\windows\launcher.py
Write-Host "built dist\sudo-make-music-portable.exe"
