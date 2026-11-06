"""VirusTotal helpers. Files are NEVER uploaded: only a SHA-256 fingerprint is looked up.

Without an API key you get a link to the file's VirusTotal page (works in any browser). With a free API key
(from your VirusTotal account) the app can also read the result itself. 'Not found' just means nobody has uploaded
that exact file yet; it is not a warning."""
from __future__ import annotations

import os
from dataclasses import dataclass

from . import netutil

API_BASE = "https://www.virustotal.com/api/v3"
GUI_BASE = "https://www.virustotal.com/gui/file"
VT_SUFFIXES = ("virustotal.com",)


def gui_url(sha256: str) -> str:
    if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256.lower()):
        raise ValueError("not a SHA-256")
    return f"{GUI_BASE}/{sha256.lower()}"


@dataclass
class VtResult:
    status: str      # found | unknown | no_key | rate_limited | error
    detail: str = ""
    malicious: int = 0
    suspicious: int = 0
    harmless: int = 0
    undetected: int = 0
    url: str = ""

    def summary(self) -> str:
        if self.status == "found":
            total = self.malicious + self.suspicious + self.harmless + self.undetected
            return f"VirusTotal: {self.malicious} malicious, {self.suspicious} suspicious out of {total} engines"
        return {"unknown": "VirusTotal has not seen this exact file yet (not a warning).",
                "no_key": "No VirusTotal API key set: use the link to look it up in your browser.",
                "rate_limited": "VirusTotal rate limit reached (free keys allow 4 lookups a minute). Try again shortly."}.get(
                    self.status, f"VirusTotal lookup failed: {self.detail}")


def lookup(sha256: str, api_key: str | None = None, api_base: str = API_BASE, allow_local_http: bool = False) -> VtResult:
    api_key = api_key or os.environ.get("VT_API_KEY", "")
    url = gui_url(sha256)
    if not api_key:
        return VtResult("no_key", url=url)
    try:
        doc, _ = netutil.fetch_json(f"{api_base}/files/{sha256.lower()}", secret_headers={"x-apikey": api_key},
                                    suffixes=VT_SUFFIXES, allow_local_http=allow_local_http)
        stats = doc["data"]["attributes"]["last_analysis_stats"]
        return VtResult("found", url=url, malicious=int(stats.get("malicious", 0)), suspicious=int(stats.get("suspicious", 0)),
                        harmless=int(stats.get("harmless", 0)), undetected=int(stats.get("undetected", 0)))
    except netutil.HTTPError as e:
        if e.code == 404:
            return VtResult("unknown", url=url)
        if e.code == 429:
            return VtResult("rate_limited", url=url)
        if e.code in (401, 403):
            return VtResult("error", "the API key was rejected", url=url)
        return VtResult("error", f"HTTP {e.code}", url=url)
    except Exception as e:
        return VtResult("error", f"{type(e).__name__}: {e}", url=url)
