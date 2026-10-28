import subprocess
import sys

CODE = """
import sys
class Bad:
    def write(self, s): raise OSError('invalid handle')
    def flush(self): raise OSError('invalid handle')
sys.stdout = Bad(); sys.stderr = Bad()
from sudo_make_music.stdio import ensure_std_streams
assert ensure_std_streams() is True
import kivy          # RecursionError here without the fix
print('IMPORT_OK', file=sys.__stdout__)
"""


def test_kivy_imports_with_unusable_streams():
    r = subprocess.run([sys.executable, "-I", "-c", CODE], capture_output=True, text=True, timeout=120,
                       env={"KIVY_NO_ARGS": "1", "PATH": "", "PYTHONPATH": ":".join(sys.path)})
    assert "IMPORT_OK" in r.stdout, r.stdout + r.stderr


def test_none_streams_are_replaced():
    r = subprocess.run([sys.executable, "-I", "-c",
                        "import sys; sys.stdout=None; sys.stderr=None\n"
                        "from sudo_make_music.stdio import ensure_std_streams\n"
                        "print(ensure_std_streams(), sys.stderr is not None, file=sys.__stderr__)"],
                       capture_output=True, text=True, timeout=60, env={"PYTHONPATH": ":".join(sys.path)})
    assert "True True" in r.stderr, r.stdout + r.stderr


def test_normal_streams_are_left_alone():
    from sudo_make_music.stdio import ensure_std_streams
    assert ensure_std_streams() is False
