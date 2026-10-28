"""PyInstaller entry point for the portable Windows exe."""
import runpy
import sys

if len(sys.argv) > 2 and sys.argv[1] == "--run-module":   # used by runtime.py to run pip
    mod = sys.argv[2]
    sys.argv = [mod] + sys.argv[3:]
    runpy.run_module(mod, run_name="__main__", alter_sys=True)
else:
    from sudo_make_music.__main__ import main
    main()
