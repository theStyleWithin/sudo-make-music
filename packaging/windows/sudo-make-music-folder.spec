# PyInstaller spec for the unpacked-folder build: no self-extracting exe, so antivirus tools flag it far less often.
# Build: pyinstaller --noconfirm --distpath dist --workpath build/pyinstaller-folder packaging/windows/sudo-make-music-folder.spec
import os
from kivy_deps import sdl2, glew
from kivy.tools.packaging.pyinstaller_hooks import get_deps_minimal, hookspath, runtime_hooks

kv = get_deps_minimal(video=None, camera=None, spelling=None)
ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
a = Analysis([os.path.join(SPECPATH, "launcher.py")], pathex=[ROOT], datas=[],
             hiddenimports=kv["hiddenimports"] + ["sudo_make_music.ui.app", "pip", "lameenc"],
             excludes=kv["excludes"] + ["tkinter", "unittest", "test"],
             hookspath=hookspath(), runtime_hooks=runtime_hooks())
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="sudo-make-music", console=False, upx=False,
          icon=os.path.join(SPECPATH, "icon.ico"), version=os.path.join(SPECPATH, "version_info.txt"))
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas,
               *[Tree(p) for p in sdl2.dep_bins + glew.dep_bins],
               strip=False, upx=False, name="sudo-make-music")
