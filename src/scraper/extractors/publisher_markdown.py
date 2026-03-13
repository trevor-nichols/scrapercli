from __future__ import annotations

import time
from typing import Any

import yaml

from ..html.markdown import MarkdownDocumentBuilder, MarkdownRenderer
from ..http.client import HttpClient
from ..models import CandidateKind, ContentKind, DiscoveryBundle, ExtractionAttempt, ExtractionMode, MarkdownDocument, PageMetadata
from ..observability.recorder import DecisionRecorder
from ..utils.text import first_meaningful_line, normalize_line_whitespace, normalize_whitespace


MARKDOWN_SOURCE_KINDS = {CandidateKind.LINKED_MARKDOWN, CandidateKind.MARKDOWN_TWIN, CandidateKind.LLMS_FULL}


class PublisherMarkdownExtractor:
    mode_name = ExtractionMode.PUBLISHER_MARKDOWN

    def __init__(self, http_client: HttpClient, recorder: DecisionRecorder, include_frontmatter: bool = True) -> None:
        self.http_client = http_client
        self.recorder = recorder
        self.renderer = MarkdownRenderer()
        self.builder = MarkdownDocumentBuilder(self.renderer, include_frontmatter=include_frontmatter)

    def run(self, bundle: DiscoveryBundle) -> ExtractionAttempt:
        start = time.perf_counter()
        candidates = [candidate for candidate in bundle.candidates if candidate.kind in MARKDOWN_SOURCE_KINDS and candidate.url]
        attempt = ExtractionAttempt(mode=self.mode_name, url=bundle.normalized_url, candidate_urls=[candidate.url or "" for candidate in candidates])
        if not candidates:
            attempt.outcome = "no_markdown_candidates"
            attempt.observed_signals.append("no_publisher_markdown")
            attempt.elapsed_ms = int((time.perf_counter() - start) * 1000)
            return attempt
        for candidate in candidates:
            snapshot = self.http_client.fetch(candidate.url or bundle.normalized_url, conditional=True, allow_status={404})
            if snapshot.status_code != 200 or not snapshot.text:
                continue
            if not (snapshot.is_markdown or snapshot.content_type is None or snapshot.content_type.startswith("text/plain")):
                continue
            frontmatter, body = split_frontmatter(snapshot.text)
            metadata = merge_markdown_metadata(bundle.metadata, snapshot.final_url, frontmatter, body)
            extra = {"extraction_method": self.mode_name.value, "source_kind": candidate.kind.value}
            normalized_body = body if contains_code_fences(body) else normalize_line_whitespace(body)
            markdown = snapshot.text.strip() if frontmatter and snapshot.text.lstrip().startswith("---") else self.builder.build(metadata, normalized_body, extra)
            attempt.document = MarkdownDocument(
                markdown=markdown.strip(),
                metadata=metadata,
                content_kind=ContentKind.MARKDOWN,
                source_kind=candidate.kind,
                diagnostics={"candidate_confidence": candidate.confidence, "candidate_evidence": candidate.evidence, "frontmatter_keys": sorted(frontmatter.keys())},
            )
            attempt.success = True
            attempt.outcome = "publisher_markdown_selected"
            attempt.observed_signals.extend(candidate.evidence)
            break
        if not attempt.success:
            attempt.outcome = "publisher_markdown_unusable"
            attempt.observed_signals.append("markdown_candidates_failed_fetch_or_validation")
        attempt.elapsed_ms = int((time.perf_counter() - start) * 1000)
        return attempt



def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    stripped = text.lstrip()
    if not stripped.startswith("---\n"):
        return {}, text
    end = stripped.find("\n---\n", 4)
    if end == -1:
        return {}, text
    frontmatter_raw = stripped[4:end]
    body = stripped[end + 5 :]
    try:
        payload = yaml.safe_load(frontmatter_raw) or {}
        if not isinstance(payload, dict):
            payload = {}
    except yaml.YAMLError:
        payload = {}
    return payload, body



def merge_markdown_metadata(existing: PageMetadata | None, source_url: str, frontmatter: dict[str, Any], body: str) -> PageMetadata:
    metadata = existing.model_copy(deep=True) if existing else PageMetadata(source_url=source_url)
    metadata.source_url = source_url
    metadata.canonical_url = str(frontmatter.get("canonical_url") or metadata.canonical_url or source_url)
    metadata.title = normalize_whitespace(str(frontmatter.get("title") or metadata.title or extract_title_from_markdown(body) or "")) or metadata.title
    metadata.description = normalize_whitespace(str(frontmatter.get("description") or metadata.description or "")) or metadata.description
    metadata.author = normalize_whitespace(str(frontmatter.get("author") or metadata.author or "")) or metadata.author
    metadata.published_at = str(frontmatter.get("published_at") or metadata.published_at or "") or metadata.published_at
    metadata.modified_at = str(frontmatter.get("modified_at") or metadata.modified_at or "") or metadata.modified_at
    metadata.language = str(frontmatter.get("language") or metadata.language or "") or metadata.language
    known_fields = set(metadata.__class__.model_fields)
    metadata.extra = {**metadata.extra, **{str(k): v for k, v in frontmatter.items() if k not in known_fields}}
    return metadata



def extract_title_from_markdown(markdown: str) -> str | None:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return normalize_whitespace(line[2:])
    line = first_meaningful_line(markdown)
    if line and len(line) < 120:
        return normalize_whitespace(line.lstrip("# "))
    return None



def contains_code_fences(text: str) -> bool:
    return "```" in text
