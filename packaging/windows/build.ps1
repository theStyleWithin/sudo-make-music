# Builds dist\sudo-make-music-portable.exe (single file) and dist\sudo-make-music\ (folder). Windows, Python 3.12.
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
Run 'python -m pip install --upgrade pip'
# Our own bootloader: PyInstaller's stock prebuilt loader is shared by lots of malware, so some antivirus engines
# match it by signature. Compiling it here gives a different binary. If compiling fails we fall back to the stock one.
$env:PYINSTALLER_COMPILE_BOOTLOADER = "1"
try {
    Run 'python -m pip install --no-binary pyinstaller --no-cache-dir --force-reinstall pyinstaller'
    Run 'python -m PyInstaller --version'
    Write-Host "::notice title=bootloader::using a bootloader compiled from source on this machine"
} catch {
    Write-Host "::warning title=bootloader::compiling the bootloader failed ($_); using the stock PyInstaller bootloader"
    Remove-Item Env:PYINSTALLER_COMPILE_BOOTLOADER -ErrorAction SilentlyContinue
    Run 'python -m pip install --upgrade --force-reinstall pyinstaller'
}
Run 'python -m pip install ".[windows]"'
Run 'python -m PyInstaller --noconfirm --distpath dist --workpath build\pyinstaller packaging\windows\sudo-make-music.spec'
Run 'python -m PyInstaller --noconfirm --distpath dist --workpath build\pyinstaller-folder packaging\windows\sudo-make-music-folder.spec'
foreach ($f in 'dist\sudo-make-music-portable.exe', 'dist\sudo-make-music\sudo-make-music.exe') {
    if (-not (Test-Path $f)) { throw "PyInstaller finished but $f is missing" }
}
Write-Host "built dist\sudo-make-music-portable.exe and dist\sudo-make-music\"
