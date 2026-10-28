# Builds dist\sudo-make-music-portable.exe  (run on Windows, Python 3.12 recommended)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\..")
function Run($cmd) {
    Write-Host ">> $cmd"
    Invoke-Expression $cmd
    if ($LASTEXITCODE -ne 0) { throw "failed ($LASTEXITCODE): $cmd" }
}
Run 'python -m pip install --upgrade pip pyinstaller'
Run 'python -m pip install ".[windows]"'
Run 'python -m PyInstaller --noconfirm --distpath dist --workpath build\pyinstaller packaging\windows\sudo-make-music.spec'
if (-not (Test-Path dist\sudo-make-music-portable.exe)) { throw "PyInstaller finished but the exe is missing" }
Write-Host "built dist\sudo-make-music-portable.exe"
