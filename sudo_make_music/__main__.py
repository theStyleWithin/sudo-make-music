import argparse
import logging

from .server import serve


def main() -> None:
    ap = argparse.ArgumentParser(prog="sudo-make-music", description="Offline AI music generation")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7860)
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO)
    serve(a.host, a.port)


if __name__ == "__main__":
    main()
