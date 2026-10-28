# PyInstaller spec for the portable exe (Kivy needs its SDL2/GLEW DLL trees added).
# Build: pyinstaller --noconfirm --distpath dist --workpath build/pyinstaller packaging/windows/sudo-make-music.spec
import os
from kivy_deps import sdl2, glew
from kivy.tools.packaging.pyinstaller_hooks import get_deps_minimal, hookspath, runtime_hooks

kv = get_deps_minimal(video=None, camera=None, spelling=None)
ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))      # SPECPATH = this file's folder
a = Analysis([os.path.join(SPECPATH, "launcher.py")], pathex=[ROOT], datas=[],
             hiddenimports=kv["hiddenimports"] + ["sudo_make_music.ui.app", "pip", "lameenc"],
             excludes=kv["excludes"] + ["tkinter", "unittest", "test"],   # unused: fewer modules for scanners to look at
              hookspath=hookspath(), runtime_hooks=runtime_hooks())
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.zipfiles, a.datas,
          *[Tree(p) for p in sdl2.dep_bins + glew.dep_bins],
          name="sudo-make-music-portable", console=False, upx=False,   # no UPX packer (a classic AV trigger)
          icon=os.path.join(SPECPATH, "icon.ico"), version=os.path.join(SPECPATH, "version_info.txt"))
