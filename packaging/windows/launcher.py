"""PyInstaller entry point for the portable Windows exe."""
import runpy
import sys

# The frozen exe has no `python -m`, so the in-app installer runs pip through this hook.
# It is deliberately limited to pip: the exe must not be a generic "run any module" launcher.
ALLOWED_MODULES = {"pip"}

if len(sys.argv) > 2 and sys.argv[1] == "--run-module" and sys.argv[2] in ALLOWED_MODULES:
    mod = sys.argv[2]
    sys.argv = [mod] + sys.argv[3:]
    runpy.run_module(mod, run_name="__main__", alter_sys=True)
else:
    from sudo_make_music.__main__ import main
    main()
