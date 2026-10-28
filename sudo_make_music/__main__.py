import argparse
import logging
import secrets

from . import runtime


def main() -> None:
    ap = argparse.ArgumentParser(prog="sudo-make-music", description="Offline AI music generation")
    ap.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to allow the Android app / other devices")
    ap.add_argument("--port", type=int, default=7860)
    ap.add_argument("--token", help="require this token (auto-generated when --host is not 127.0.0.1)")
    ap.add_argument("--open", action="store_true", help="open the UI in your browser")
    ap.add_argument("--install-backend", nargs="?", const="cu126", metavar="CUDA",
                    help="install torch+ACE-Step for the user (cu126|cu124|cu121|cpu), then exit")
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
    runtime.activate()
    from .server import serve
    token = a.token or (None if a.host == "127.0.0.1" else secrets.token_urlsafe(12))
    serve(a.host, a.port, token=token, open_browser=a.open)


if __name__ == "__main__":
    main()
