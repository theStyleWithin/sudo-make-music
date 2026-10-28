"""SQLite generation history."""
from __future__ import annotations

import json
import sqlite3
import threading
import time

from . import paths

_SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
  id TEXT PRIMARY KEY, created REAL, backend TEXT, prompt TEXT, lyrics TEXT,
  duration REAL, seed INTEGER, mode TEXT, status TEXT, error TEXT,
  elapsed REAL, params TEXT
)"""


class History:
    def __init__(self, db_path=None):
        self._db = sqlite3.connect(str(db_path or paths.home() / "history.db"), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute(_SCHEMA)
            self._db.commit()

    def add(self, **row) -> None:
        row.setdefault("created", time.time())
        row["params"] = json.dumps(row.get("params") or {})
        cols = ",".join(row)
        with self._lock:
            self._db.execute(f"INSERT OR REPLACE INTO history ({cols}) VALUES ({','.join('?' * len(row))})",
                             list(row.values()))
            self._db.commit()

    def list(self, limit: int = 200) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM history ORDER BY created DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["params"] = json.loads(d["params"] or "{}")
            out.append(d)
        return out

    def get(self, id_: str) -> dict | None:
        with self._lock:
            r = self._db.execute("SELECT * FROM history WHERE id=?", (id_,)).fetchone()
        return dict(r) if r else None

    def delete(self, id_: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM history WHERE id=?", (id_,))
            self._db.commit()
