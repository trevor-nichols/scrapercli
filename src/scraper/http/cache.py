from __future__ import annotations

import json
from pathlib import Path


class ConditionalRequestCache:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.data: dict[str, dict[str, str]] = {}
        self._load()

    def _load(self) -> None:
        if self.path is None:
            self.data = {}
            return
        if self.path.exists():
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {}
            self.data = payload if isinstance(payload, dict) else {}
        else:
            self.data = {}

    def get_headers(self, url: str) -> dict[str, str]:
        entry = self.data.get(url, {})
        headers: dict[str, str] = {}
        if etag := entry.get("etag"):
            headers["If-None-Match"] = etag
        if modified := entry.get("last_modified"):
            headers["If-Modified-Since"] = modified
        return headers

    def update(self, url: str, *, etag: str | None = None, last_modified: str | None = None) -> None:
        if not etag and not last_modified:
            return
        current = self.data.get(url, {})
        if etag:
            current["etag"] = etag
        if last_modified:
            current["last_modified"] = last_modified
        self.data[url] = current
        self._save()

    def _save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
