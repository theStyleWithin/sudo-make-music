"""Local web server (stdlib only). Binds to 127.0.0.1 by default."""
from __future__ import annotations

import hmac
import json
import mimetypes
import re
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from . import runtime
from .engine import Engine

WEB = Path(__file__).parent / "web"


def make_handler(engine: Engine, token: str | None = None):
    installer = runtime.Installer()

    class H(BaseHTTPRequestHandler):
        server_version = "sudo-make-music"

        def log_message(self, *a):  # quiet
            pass

        # -- helpers
        def _json(self, obj, code=200):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        def _file(self, path: Path, download_name: str | None = None):
            size = path.stat().st_size
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            start, end, code = 0, size - 1, 200
            rng = self.headers.get("Range")
            if rng and (m := re.match(r"bytes=(\d*)-(\d*)", rng)):
                if m.group(1):
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else end
                elif m.group(2):
                    start = max(0, size - int(m.group(2)))
                code = 206
            end = min(end, size - 1)
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            if code == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            if download_name:
                self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
            self.end_headers()
            with open(path, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    buf = f.read(min(1 << 20, left))
                    if not buf:
                        break
                    self.wfile.write(buf)
                    left -= len(buf)

        def _guard(self, fn):
            try:
                fn()
            except (ValueError, KeyError) as e:
                self._json({"error": str(e)}, 400)
            except RuntimeError as e:
                self._json({"error": str(e)}, 409)
            except (BrokenPipeError, ConnectionResetError):
                pass

        # -- routes
        def _authed(self) -> bool:
            """Optional shared token (for LAN/Android use). Accepts ?token=, Bearer header or cookie."""
            if not token:
                return True
            q = parse_qs(urlparse(self.path).query).get("token", [""])[0]
            auth = self.headers.get("Authorization", "")
            ck = self.headers.get("Cookie", "")
            ok = (hmac.compare_digest(q, token) or hmac.compare_digest(auth, "Bearer " + token)
                  or f"smm_token={token}" in [c.strip() for c in ck.split(";")])
            if not ok:
                self._json({"error": "unauthorized: open the URL with ?token=..."}, 401)
            elif q:
                self._set_cookie = True
            return ok

        def end_headers(self):
            if getattr(self, "_set_cookie", False):
                self.send_header("Set-Cookie", f"smm_token={token}; Path=/; HttpOnly; SameSite=Strict")
            super().end_headers()

        def do_GET(self):
            self._set_cookie = False
            if self._authed():
                self._guard(self._get)

        def do_POST(self):
            self._set_cookie = False
            if self._authed():
                self._guard(self._post)

        def do_DELETE(self):
            self._set_cookie = False
            if self._authed():
                self._guard(self._delete)

        def _get(self):
            u = urlparse(self.path)
            p = u.path
            if p in ("/", "/index.html"):
                return self._file(WEB / "index.html")
            if p == "/api/status":
                return self._json(engine.status())
            if p == "/api/settings":
                from dataclasses import asdict
                return self._json(asdict(engine.store.value))
            if p == "/api/install-backend":
                return self._json(installer.snapshot())
            if p == "/api/history":
                return self._json(engine.history.list())
            if m := re.fullmatch(r"/api/jobs/(\w+)", p):
                job = engine.jobs.get(m.group(1))
                return self._json(job.to_dict(), 200) if job else self._json({"error": "not found"}, 404)
            if m := re.fullmatch(r"/audio/(\w+)\.(wav|mp3)", p):
                f = engine.output_path(m.group(1), m.group(2))
                if not f:
                    return self._json({"error": "not found"}, 404)
                dl = parse_qs(u.query).get("download")
                return self._file(f, f.name if dl else None)
            self._json({"error": "not found"}, 404)

        def _post(self):
            p = urlparse(self.path).path
            data = self._body()
            if p == "/api/generate":
                job = engine.submit(data.get("prompt", ""), data.get("lyrics", ""), int(data.get("duration", 60)))
                return self._json(job.to_dict())
            if p == "/api/cancel":
                return self._json({"ok": engine.cancel(data.get("id", ""))})
            if p == "/api/settings":
                engine.store.value.update(data)
                engine.store.save()
                return self._json(engine.status())
            if p == "/api/install-backend":
                installer.start(str(data.get("cuda", "cu126")))
                return self._json(installer.snapshot())
            if p == "/api/unload":
                engine.unload_all()
                return self._json({"ok": True})
            self._json({"error": "not found"}, 404)

        def _delete(self):
            if m := re.fullmatch(r"/api/history/(\w+)", urlparse(self.path).path):
                engine.delete(m.group(1))
                return self._json({"ok": True})
            self._json({"error": "not found"}, 404)

    return H


def serve(host: str = "127.0.0.1", port: int = 7860, engine: Engine | None = None,
          token: str | None = None, open_browser: bool = False) -> None:
    engine = engine or Engine()
    httpd = ThreadingHTTPServer((host, port), make_handler(engine, token))
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{port}"
    print(f"sudo-make-music running at {url}  (offline, local only)" if host == "127.0.0.1" else
          f"sudo-make-music listening on {host}:{port} - reachable from your network"
          + (f"; use ?token={token}" if token else " WITHOUT a token (anyone on the network can use it)"))
    if open_browser:
        import webbrowser
        webbrowser.open(url + (f"/?token={token}" if token else ""))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        engine.shutdown()
