from __future__ import annotations

import json
import math
import time
from typing import Any

from ..html.markdown import MarkdownDocumentBuilder, MarkdownRenderer
from ..http.client import HttpClient
from ..models import CandidateKind, ContentKind, DiscoveryBundle, ExtractionAttempt, ExtractionMode, MarkdownDocument, PageMetadata
from ..observability.recorder import DecisionRecorder
from .publisher_markdown import merge_markdown_metadata, split_frontmatter
from .structured import collect_structured_candidates, kind_priority, merge_structured_metadata, structured_candidate_to_markdown


REPLAY_KINDS = {CandidateKind.API_ENDPOINT, CandidateKind.GRAPHQL_ENDPOINT, CandidateKind.BROWSER_CAPTURED_ENDPOINT}


class HTTPReplayExtractor:
    mode_name = ExtractionMode.HTTP_REPLAY

    def __init__(self, http_client: HttpClient, recorder: DecisionRecorder, include_frontmatter: bool = True) -> None:
        self.http_client = http_client
        self.recorder = recorder
        self.renderer = MarkdownRenderer()
        self.builder = MarkdownDocumentBuilder(self.renderer, include_frontmatter=include_frontmatter)

    def run(self, bundle: DiscoveryBundle) -> ExtractionAttempt:
        start = time.perf_counter()
        candidates = [candidate for candidate in bundle.candidates if candidate.kind in REPLAY_KINDS and candidate.url]
        attempt = ExtractionAttempt(mode=self.mode_name, url=bundle.normalized_url, candidate_urls=[candidate.url or "" for candidate in candidates])
        if not candidates:
            attempt.outcome = "no_replay_candidates"
            attempt.observed_signals.append("no_http_replay_candidates")
            attempt.elapsed_ms = int((time.perf_counter() - start) * 1000)
            return attempt
        best_doc: MarkdownDocument | None = None
        best_score = -math.inf
        for candidate in candidates:
            if candidate.kind == CandidateKind.GRAPHQL_ENDPOINT and not candidate.body:
                continue
            snapshot = self.http_client.fetch(candidate.url or bundle.normalized_url, method=candidate.method, headers=candidate.headers, content=candidate.body, conditional=candidate.method.upper() == "GET", allow_status={404, 405})
            if snapshot.status_code != 200 or not snapshot.text:
                continue
            if snapshot.is_json:
                payload = parse_json_safe(snapshot.text)
                if payload is None:
                    continue
                structured_candidates = collect_structured_candidates(payload)
                if not structured_candidates:
                    continue
                structured_candidates.sort(key=lambda item: (item.score, kind_priority(item.kind)), reverse=True)
                chosen = structured_candidates[0]
                metadata = merge_structured_metadata(bundle.metadata, snapshot.final_url, chosen)
                markdown_body = structured_candidate_to_markdown(chosen, self.renderer, base_url=snapshot.final_url)
                markdown = self.builder.build(metadata, markdown_body, extra_frontmatter={"extraction_method": self.mode_name.value, "source_kind": candidate.kind.value, "replayed_url": snapshot.final_url})
                score = chosen.score
                document = MarkdownDocument(markdown=markdown, metadata=metadata, content_kind=chosen.kind, source_kind=candidate.kind, diagnostics={"replayed_url": snapshot.final_url, "structured_path": chosen.path, "structured_score": chosen.score, "payload_kind": candidate.kind.value})
            elif snapshot.is_markdown:
                frontmatter, body = split_frontmatter(snapshot.text)
                metadata = merge_markdown_metadata(bundle.metadata, snapshot.final_url, frontmatter, body)
                document = MarkdownDocument(markdown=snapshot.text.strip(), metadata=metadata, content_kind=ContentKind.MARKDOWN, source_kind=candidate.kind, diagnostics={"replayed_url": snapshot.final_url, "payload_kind": candidate.kind.value})
                score = 18.0 + len(snapshot.text) / 500
            elif snapshot.is_html:
                metadata = bundle.metadata.model_copy(deep=True) if bundle.metadata else PageMetadata(source_url=snapshot.final_url, canonical_url=snapshot.final_url)
                markdown_body = self.renderer.render_html(snapshot.text, snapshot.final_url)
                markdown = self.builder.build(metadata, markdown_body, extra_frontmatter={"extraction_method": self.mode_name.value, "source_kind": candidate.kind.value, "replayed_url": snapshot.final_url})
                document = MarkdownDocument(markdown=markdown, metadata=metadata, content_kind=ContentKind.HTML, source_kind=candidate.kind, diagnostics={"replayed_url": snapshot.final_url, "payload_kind": candidate.kind.value})
                score = 12.0 + len(markdown_body) / 500
            else:
                continue
            if score > best_score:
                best_score = score
                best_doc = document
                attempt.observed_signals.extend(candidate.evidence)
        if best_doc is not None:
            attempt.success = True
            attempt.document = best_doc
            attempt.outcome = "http_replay_selected"
        else:
            attempt.outcome = "http_replay_unusable"
            attempt.observed_signals.append("http_replay_failed")
        attempt.elapsed_ms = int((time.perf_counter() - start) * 1000)
        return attempt



def parse_json_safe(text: str) -> Any | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None
