from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..utils.hashing import sha256_bytes, sha256_text
from ..utils.url import safe_filename_from_url


@dataclass(frozen=True)
class ArtifactPersistencePolicy:
    save_raw_sources: bool = True
    save_metadata_sidecar: bool = True
    save_state: bool = True
    save_decision_log: bool = True
    save_run_documents: bool = True

    @classmethod
    def minimal(cls) -> ArtifactPersistencePolicy:
        return cls(
            save_raw_sources=False,
            save_metadata_sidecar=False,
            save_state=False,
            save_decision_log=False,
            save_run_documents=False,
        )

    @classmethod
    def verbose(cls, *, save_raw_sources: bool = True, save_metadata_sidecar: bool = True) -> ArtifactPersistencePolicy:
        return cls(
            save_raw_sources=save_raw_sources,
            save_metadata_sidecar=save_metadata_sidecar,
            save_state=True,
            save_decision_log=True,
            save_run_documents=True,
        )


class ArtifactStore:
    def __init__(self, root_dir: Path, *, policy: ArtifactPersistencePolicy | None = None) -> None:
        self.policy = policy or ArtifactPersistencePolicy()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.run_id = timestamp
        self.root_dir = root_dir / timestamp
        self.raw_dir = self.root_dir / "raw" if self.policy.save_raw_sources else None
        self.markdown_dir = self.root_dir / "markdown"
        self.metadata_dir = self.root_dir / "metadata" if self.policy.save_metadata_sidecar else None
        self.state_dir = self.root_dir / "state" if self.policy.save_state else None
        self.log_dir = self.root_dir / "logs" if self.policy.save_decision_log else None
        paths = [self.root_dir, self.markdown_dir]
        for optional_path in (self.raw_dir, self.metadata_dir, self.state_dir, self.log_dir):
            if optional_path is not None:
                paths.append(optional_path)
        for path in paths:
            path.mkdir(parents=True, exist_ok=True)

    @property
    def decisions_path(self) -> Path | None:
        if self.log_dir is None:
            return None
        return self.log_dir / "decisions.jsonl"

    @property
    def conditional_cache_path(self) -> Path | None:
        if self.state_dir is None:
            return None
        return self.state_dir / "validators.json"

    @property
    def repetition_store_path(self) -> Path | None:
        if self.state_dir is None:
            return None
        return self.state_dir / "repetition.json"

    def save_response(self, url: str, method: str, body: bytes, headers: dict[str, Any], status_code: int) -> tuple[Path | None, str]:
        body_hash = sha256_bytes(body)
        if self.raw_dir is None:
            return None, body_hash
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

    def save_metadata(self, url: str, metadata: dict[str, Any]) -> Path | None:
        if self.metadata_dir is None:
            return None
        prefix = safe_filename_from_url(url)
        serialized = json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True)
        digest = sha256_text(serialized)
        target = self.metadata_dir / f"{prefix}__{digest[:16]}.json"
        target.write_text(serialized, encoding="utf-8")
        return target

    def save_json_document(self, name: str, payload: dict[str, Any]) -> Path | None:
        if not self.policy.save_run_documents:
            return None
        target = self.root_dir / name
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return target
