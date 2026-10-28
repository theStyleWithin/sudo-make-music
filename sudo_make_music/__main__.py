import argparse
import logging

from . import runtime


def main() -> None:
    ap = argparse.ArgumentParser(prog="sudo-make-music", description="Offline AI music generation")
    ap.add_argument("--install-backend", nargs="?", const="cu126", metavar="CUDA",
                    help="install torch+ACE-Step for this user (cu126|cu124|cu121|cpu), then exit")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO)
    if a.install_backend:
        import subprocess
        for cmd in runtime.install_commands(a.install_backend):
            print("$", " ".join(cmd))
            if subprocess.call(cmd) != 0:
                raise SystemExit(1)
        return
    from .ui.app import run
    run()


if __name__ == "__main__":
    main()
