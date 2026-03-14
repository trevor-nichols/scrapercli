from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from ..models import RepetitionStore
from ..utils.hashing import sha256_text
from ..utils.text import normalize_whitespace


class RepetitionIndex:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.store_by_host: dict[str, RepetitionStore] = {}
        self._load()

    def _load(self) -> None:
        if self.path is None:
            return
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        for host, payload in raw.items():
            self.store_by_host[host] = RepetitionStore.model_validate(payload)

    def save(self) -> None:
        if self.path is None:
            return
        payload = {host: store.model_dump(mode="python") for host, store in self.store_by_host.items()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    def score(self, host: str, signature: str) -> float:
        store = self.store_by_host.get(host)
        if not store or store.pages_seen <= 0:
            return 0.0
        count = store.signatures.get(signature, 0)
        return round(count / max(1, store.pages_seen), 4)

    def update_from_html(self, url: str, html: str) -> None:
        host = urlparse(url).netloc
        if not host:
            return
        soup = BeautifulSoup(html, "lxml")
        store = self.store_by_host.setdefault(host, RepetitionStore(host=host))
        store.pages_seen += 1
        for node in self._candidate_nodes(soup):
            signature = node_signature(node)
            if signature:
                store.signatures[signature] = store.signatures.get(signature, 0) + 1
        self.save()

    def _candidate_nodes(self, soup: BeautifulSoup) -> Iterable[Tag]:
        tags = soup.find_all(["header", "footer", "nav", "aside", "main", "article", "section", "div"])
        for tag in tags:
            if not isinstance(tag, Tag):
                continue
            if depth(tag) > 4:
                continue
            yield tag



def depth(node: Tag) -> int:
    current = node
    value = 0
    while current.parent is not None and isinstance(current.parent, Tag):
        value += 1
        current = current.parent
    return value



def node_signature(node: Tag) -> str:
    text = normalize_whitespace(node.get_text(" ", strip=True))[:200]
    classes = node.get("class") or []
    class_token = "|".join(sorted(str(item) for item in classes)[:6])
    child_tags = ",".join(child.name for child in node.find_all(recursive=False)[:12] if isinstance(child, Tag))
    anchor_labels = sorted(
        normalize_whitespace(anchor.get_text(" ", strip=True))[:40]
        for anchor in node.find_all("a")[:10]
        if normalize_whitespace(anchor.get_text(" ", strip=True))
    )
    raw = f"{node.name}|{class_token}|{child_tags}|{'|'.join(anchor_labels)}|{text[:120]}"
    return sha256_text(raw)
