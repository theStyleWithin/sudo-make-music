# Builds dist\sudo-make-music-portable.exe  (run on Windows, Python 3.12 recommended)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\..")
# CI/headless machines only have a GDI OpenGL 1.1 driver: Kivy would quit while PyInstaller inspects it.
# ANGLE (software-capable) avoids that. Real PCs are unaffected (this only applies to the build).
$env:KIVY_GL_BACKEND = "angle_sdl2"
$env:KIVY_NO_ARGS = "1"
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
