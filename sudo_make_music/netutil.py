"""Small, careful HTTP helper shared by the catalog, the downloader and the VirusTotal lookup.

Only HTTPS, only hosts on an allowlist, redirects re-checked (a download cannot be bounced to some other host),
and credentials are never forwarded across a redirect. Plain http is allowed only for localhost in tests."""
from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from urllib.error import HTTPError  # noqa: F401  (re-exported for callers)

ALLOWED_HOST_SUFFIXES = ("huggingface.co", "hf.co", "github.com", "githubusercontent.com")
USER_AGENT = "sudo-make-music"      # generic on purpose: no contact details, no version fingerprinting


class HostNotAllowed(Exception):
    pass


def ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def host_allowed(url: str, suffixes=ALLOWED_HOST_SUFFIXES, allow_local_http: bool = False) -> bool:
    u = urllib.parse.urlparse(url)
    host = (u.hostname or "").lower()
    if u.scheme == "http":
        return allow_local_http and host in ("127.0.0.1", "localhost")
    if u.scheme != "https" or not host:
        return False
    return any(host == s or host.endswith("." + s) for s in suffixes)


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, suffixes, allow_local_http):
        self.suffixes, self.allow_local_http = suffixes, allow_local_http

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not host_allowed(newurl, self.suffixes, self.allow_local_http):
            raise HostNotAllowed(f"redirect to a host that is not allowed: {urllib.parse.urlparse(newurl).hostname}")
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:   # never carry credentials to the redirect target (e.g. a CDN)
            for h in ("Authorization", "Cookie", "X-apikey"):
                new.headers.pop(h, None)
                new.unredirected_hdrs.pop(h, None)
        return new


def open_url(url: str, headers: dict | None = None, secret_headers: dict | None = None, timeout: float = 30,
             suffixes=ALLOWED_HOST_SUFFIXES, allow_local_http: bool = False):
    if not host_allowed(url, suffixes, allow_local_http):
        raise HostNotAllowed(f"{urllib.parse.urlparse(url).hostname or url} is not an allowed download host")
    opener = urllib.request.build_opener(_SafeRedirect(suffixes, allow_local_http),
                                         urllib.request.HTTPSHandler(context=ssl_context()))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    for k, v in (secret_headers or {}).items():
        req.add_unredirected_header(k, v)
    return opener.open(req, timeout=timeout)


def fetch_json(url: str, **kw):
    with open_url(url, **kw) as r:
        return json.loads(r.read(20_000_000).decode("utf-8")), dict(r.headers)
