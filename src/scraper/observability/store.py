from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..utils.hashing import sha256_bytes, sha256_text
from ..utils.url import safe_filename_from_url


class ArtifactStore:
    def __init__(self, root_dir: Path) -> None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.run_id = timestamp
        self.root_dir = root_dir / timestamp
        self.raw_dir = self.root_dir / "raw"
        self.markdown_dir = self.root_dir / "markdown"
        self.metadata_dir = self.root_dir / "metadata"
        self.state_dir = self.root_dir / "state"
        self.log_dir = self.root_dir / "logs"
        for path in [self.root_dir, self.raw_dir, self.markdown_dir, self.metadata_dir, self.state_dir, self.log_dir]:
            path.mkdir(parents=True, exist_ok=True)

    @property
    def decisions_path(self) -> Path:
        return self.log_dir / "decisions.jsonl"

    @property
    def conditional_cache_path(self) -> Path:
        return self.state_dir / "validators.json"

    @property
    def repetition_store_path(self) -> Path:
        return self.state_dir / "repetition.json"

    def save_response(self, url: str, method: str, body: bytes, headers: dict[str, Any], status_code: int) -> tuple[Path, str]:
        body_hash = sha256_bytes(body)
        prefix = safe_filename_from_url(url)
        target = self.raw_dir / f"{prefix}__{method.lower()}__{status_code}__{body_hash[:16]}.txt"
        target.write_bytes(body)
        meta_path = target.with_suffix(target.suffix + ".json")
        meta_path.write_text(
            json.dumps(
                {
                    "url": url,
                    "method": method,
                    "status_code": status_code,
                    "headers": dict(sorted((str(k), str(v)) for k, v in headers.items())),
                    "body_sha256": body_hash,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return target, body_hash

    def save_markdown(self, url: str, markdown: str) -> Path:
        prefix = safe_filename_from_url(url)
        digest = sha256_text(markdown)
        target = self.markdown_dir / f"{prefix}__{digest[:16]}.md"
        target.write_text(markdown, encoding="utf-8")
        return target

    def save_metadata(self, url: str, metadata: dict[str, Any]) -> Path:
        prefix = safe_filename_from_url(url)
        serialized = json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True)
        digest = sha256_text(serialized)
        target = self.metadata_dir / f"{prefix}__{digest[:16]}.json"
        target.write_text(serialized, encoding="utf-8")
        return target

    def save_json_document(self, name: str, payload: dict[str, Any]) -> Path:
        target = self.root_dir / name
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return target
