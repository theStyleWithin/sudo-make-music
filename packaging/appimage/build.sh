#!/usr/bin/env bash
# Builds dist/sudo-make-music-x86_64.AppImage. Needs: python3 (+venv), curl, internet.
# Bundles a relocatable CPython + the light app (numpy only). Torch/ACE-Step are installed
# per-user on first use from inside the app (see sudo_make_music/runtime.py).
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT=$PWD
ID=io.github.theStyleWithin.SudoMakeMusic
BUILD=${BUILD_DIR:-$ROOT/build/appimage}
rm -rf "$BUILD"; mkdir -p "$BUILD"
python3 -m venv "$BUILD/tools"; "$BUILD/tools/bin/pip" install -q uv
export UV_PYTHON_INSTALL_DIR=$BUILD/uvpy
"$BUILD/tools/bin/uv" python install 3.12
PYSRC=$(ls -d "$BUILD"/uvpy/cpython-3.12.*-linux-x86_64-gnu | head -1)
A=$BUILD/AppDir
mkdir -p "$A/usr/share/applications" "$A/usr/share/metainfo" "$A/usr/share/icons/hicolor/scalable/apps"
cp -a "$PYSRC" "$A/usr/python"
"$A/usr/python/bin/python3" -m pip install -q --no-warn-script-location --target "$A/usr/app" "$ROOT"
find "$A/usr" -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
cat > "$A/AppRun" <<'RUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
export PYTHONPATH="$HERE/usr/app${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONNOUSERSITE=1
exec "$HERE/usr/python/bin/python3" -m sudo_make_music --open "$@"
RUN
chmod +x "$A/AppRun"
C=$ROOT/packaging/common
cp "$C/$ID.desktop" "$A/usr/share/applications/"
cp "$C/$ID.desktop" "$A/$ID.desktop"; sed -i 's/^Exec=.*/Exec=AppRun/' "$A/$ID.desktop"
cp "$C/$ID.svg" "$A/$ID.svg"; cp "$C/$ID.svg" "$A/.DirIcon"
cp "$C/$ID.svg" "$A/usr/share/icons/hicolor/scalable/apps/"
cp "$C/$ID.metainfo.xml" "$A/usr/share/metainfo/"
TOOL=$BUILD/appimagetool
curl -fsSL -o "$TOOL" https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
chmod +x "$TOOL"
mkdir -p "$ROOT/dist"
ARCH=x86_64 "$TOOL" --appimage-extract-and-run --no-appstream "$A" "$ROOT/dist/sudo-make-music-x86_64.AppImage"
echo "built $ROOT/dist/sudo-make-music-x86_64.AppImage"
