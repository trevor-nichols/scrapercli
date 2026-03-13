from __future__ import annotations

import math
import time
from typing import Any

from ..html.markdown import MarkdownDocumentBuilder, MarkdownRenderer
from ..models import CandidateKind, ContentKind, DiscoveryBundle, ExtractionAttempt, ExtractionMode, MarkdownDocument, PageMetadata, StructuredContentCandidate
from ..observability.recorder import DecisionRecorder
from ..utils.text import normalize_line_whitespace, normalize_whitespace


MARKDOWN_KEYS = {"markdown", "md", "mdx", "contentmarkdown", "bodymarkdown", "markdowncontent", "content_md"}
HTML_KEYS = {"html", "bodyhtml", "contenthtml", "renderedhtml", "rendered", "htmlcontent"}
TEXT_KEYS = {"articlebody", "body", "content", "text", "description", "excerpt", "summary"}
TITLE_KEYS = ["title", "headline", "name"]
AUTHOR_KEYS = ["author", "creator"]
PUBLISHED_KEYS = ["datePublished", "publishedAt", "createdAt"]
MODIFIED_KEYS = ["dateModified", "updatedAt", "modifiedAt"]
STRUCTURED_INPUT_KINDS = {CandidateKind.JSON_LD, CandidateKind.HYDRATION, CandidateKind.INLINE_STATE, CandidateKind.API_ENDPOINT}


class StructuredDataExtractor:
    mode_name = ExtractionMode.STRUCTURED_HTTP

    def __init__(self, recorder: DecisionRecorder, include_frontmatter: bool = True) -> None:
        self.recorder = recorder
        self.renderer = MarkdownRenderer()
        self.builder = MarkdownDocumentBuilder(self.renderer, include_frontmatter=include_frontmatter)

    def run(self, bundle: DiscoveryBundle) -> ExtractionAttempt:
        start = time.perf_counter()
        attempt = ExtractionAttempt(mode=self.mode_name, url=bundle.normalized_url)
        payload_candidates = [candidate for candidate in bundle.candidates if candidate.kind in STRUCTURED_INPUT_KINDS and candidate.payload is not None]
        if not payload_candidates:
            attempt.outcome = "no_inline_structured_payloads"
            attempt.observed_signals.append("no_structured_payload")
            attempt.elapsed_ms = int((time.perf_counter() - start) * 1000)
            return attempt
        best_document: MarkdownDocument | None = None
        best_score = -math.inf
        for candidate in payload_candidates:
            structured_candidates = collect_structured_candidates(candidate.payload)
            if not structured_candidates:
                continue
            structured_candidates.sort(key=lambda item: (item.score, kind_priority(item.kind)), reverse=True)
            chosen = structured_candidates[0]
            metadata = merge_structured_metadata(bundle.metadata, bundle.page.final_url if bundle.page else bundle.normalized_url, chosen)
            body_markdown = structured_candidate_to_markdown(chosen, self.renderer, base_url=bundle.page.final_url if bundle.page else bundle.normalized_url)
            markdown = self.builder.build(metadata, body_markdown, extra_frontmatter={"extraction_method": self.mode_name.value, "source_kind": candidate.kind.value})
            score = chosen.score
            if score > best_score:
                best_score = score
                best_document = MarkdownDocument(
                    markdown=markdown,
                    metadata=metadata,
                    content_kind=chosen.kind,
                    source_kind=candidate.kind,
                    diagnostics={"structured_path": chosen.path, "structured_score": chosen.score, "structured_evidence": chosen.evidence, "payload_kind": candidate.kind.value},
                )
        if best_document is not None:
            attempt.success = True
            attempt.document = best_document
            attempt.outcome = "structured_payload_selected"
            attempt.observed_signals.append("structured_candidate_selected")
        else:
            attempt.outcome = "structured_payload_unusable"
            attempt.observed_signals.append("structured_candidates_failed")
        attempt.elapsed_ms = int((time.perf_counter() - start) * 1000)
        return attempt



def kind_priority(kind: ContentKind) -> int:
    order = {ContentKind.MARKDOWN: 5, ContentKind.HTML: 4, ContentKind.BLOCKS: 3, ContentKind.TEXT: 2, ContentKind.JSON: 1}
    return order.get(kind, 0)



def collect_structured_candidates(payload: Any, path: str = "$") -> list[StructuredContentCandidate]:
    discovered: list[StructuredContentCandidate] = []

    def walk(value: Any, current_path: str, parent_meta: dict[str, Any]) -> None:
        local_meta = dict(parent_meta)
        if isinstance(value, dict):
            extracted_meta = extract_structured_metadata(value)
            local_meta = {**local_meta, **{k: v for k, v in extracted_meta.items() if v not in (None, "")}}
            for key, item in value.items():
                normalized_key = normalize_key(key)
                item_path = f"{current_path}.{key}"
                if isinstance(item, str):
                    candidate = candidate_from_scalar(normalized_key, item, item_path, local_meta)
                    if candidate is not None:
                        discovered.append(candidate)
                elif is_block_list(item):
                    discovered.append(StructuredContentCandidate(path=item_path, kind=ContentKind.BLOCKS, value=item, score=score_for_blocks(item, normalized_key, item_path), evidence=[f"blocks_key:{key}"], metadata=local_meta))
                if isinstance(item, (dict, list)):
                    walk(item, item_path, local_meta)
        elif isinstance(value, list):
            if is_block_list(value):
                discovered.append(StructuredContentCandidate(path=current_path, kind=ContentKind.BLOCKS, value=value, score=score_for_blocks(value, "blocks", current_path), evidence=["array_of_blocks"], metadata=parent_meta))
            for index, item in enumerate(value):
                walk(item, f"{current_path}[{index}]", parent_meta)

    walk(payload, path, {})
    return dedupe_structured_candidates(discovered)



def candidate_from_scalar(key: str, value: str, path: str, metadata: dict[str, Any]) -> StructuredContentCandidate | None:
    normalized = value.strip()
    if len(normalized) < 80:
        return None
    if key in MARKDOWN_KEYS:
        return StructuredContentCandidate(path=path, kind=ContentKind.MARKDOWN, value=normalized, score=score_for_scalar(normalized, base=16, markdown=True, html=False, key=key, path=path), evidence=[f"markdown_key:{key}"], metadata=metadata)
    if key in HTML_KEYS or looks_like_html(normalized):
        return StructuredContentCandidate(path=path, kind=ContentKind.HTML, value=normalized, score=score_for_scalar(normalized, base=14, markdown=False, html=True, key=key, path=path), evidence=[f"html_key:{key}" if key in HTML_KEYS else "html_like_string"], metadata=metadata)
    if key in TEXT_KEYS and len(normalized) >= 200:
        return StructuredContentCandidate(path=path, kind=ContentKind.TEXT, value=normalized, score=score_for_scalar(normalized, base=10, markdown=False, html=False, key=key, path=path), evidence=[f"text_key:{key}"], metadata=metadata)
    if len(normalized) >= 300 and sentence_ratio(normalized) >= 0.5:
        return StructuredContentCandidate(path=path, kind=ContentKind.TEXT, value=normalized, score=score_for_scalar(normalized, base=8, markdown=False, html=False, key=key, path=path), evidence=["long_sentence_text"], metadata=metadata)
    return None



def score_for_scalar(value: str, *, base: float, markdown: bool, html: bool, key: str, path: str) -> float:
    score = base
    length = len(value)
    if length >= 2000:
        score += 8
    elif length >= 800:
        score += 5
    elif length >= 300:
        score += 3
    if markdown and value.count("#") >= 1:
        score += 2
    if html and value.count("<p") >= 2:
        score += 2
    if any(fragment in path.lower() for fragment in ["pageprops", "article", "doc", "content"]):
        score += 3
    if key in {"articlebody", "body", "content"}:
        score += 2
    return round(score, 2)



def score_for_blocks(value: list[Any], key: str, path: str) -> float:
    score = 12.0
    length = len(value)
    if length >= 20:
        score += 8
    elif length >= 8:
        score += 5
    elif length >= 3:
        score += 3
    if any(fragment in path.lower() for fragment in ["content", "body", "article", "doc"]):
        score += 2
    if key in {"content", "body", "blocks"}:
        score += 2
    return round(score, 2)



def sentence_ratio(text: str) -> float:
    chunks = [chunk.strip() for chunk in text.split(".") if chunk.strip()]
    if not chunks:
        return 0.0
    sentence_like_count = sum(1 for chunk in chunks if len(chunk.split()) >= 5)
    return sentence_like_count / len(chunks)



def looks_like_html(value: str) -> bool:
    lowered = value.lower()
    return "<p" in lowered or "<div" in lowered or "<article" in lowered or "<h1" in lowered



def is_block_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, dict) and ("type" in item or "children" in item or "content" in item) for item in value[:10])



def normalize_key(key: str) -> str:
    return "".join(ch for ch in key.lower() if ch.isalnum() or ch == "_")



def extract_structured_metadata(value: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in TITLE_KEYS:
        if value.get(key):
            metadata["title"] = normalize_whitespace(str(value[key]))
            break
    for key in AUTHOR_KEYS:
        author = value.get(key)
        if author:
            if isinstance(author, dict):
                metadata["author"] = normalize_whitespace(str(author.get("name") or author.get("title") or author))
            elif isinstance(author, list):
                pieces = []
                for item in author:
                    if isinstance(item, dict):
                        pieces.append(normalize_whitespace(str(item.get("name") or item)))
                    else:
                        pieces.append(normalize_whitespace(str(item)))
                metadata["author"] = ", ".join(dict.fromkeys(piece for piece in pieces if piece))
            else:
                metadata["author"] = normalize_whitespace(str(author))
            break
    for key in PUBLISHED_KEYS:
        if value.get(key):
            metadata["published_at"] = str(value[key])
            break
    for key in MODIFIED_KEYS:
        if value.get(key):
            metadata["modified_at"] = str(value[key])
            break
    return metadata



def dedupe_structured_candidates(candidates: list[StructuredContentCandidate]) -> list[StructuredContentCandidate]:
    deduped: dict[tuple[str, str], StructuredContentCandidate] = {}
    for candidate in candidates:
        key = (candidate.kind.value, normalize_whitespace(str(candidate.value))[:200])
        current = deduped.get(key)
        if current is None or candidate.score > current.score:
            deduped[key] = candidate
    return list(deduped.values())



def merge_structured_metadata(existing: PageMetadata | None, source_url: str, candidate: StructuredContentCandidate) -> PageMetadata:
    metadata = existing.model_copy(deep=True) if existing else PageMetadata(source_url=source_url)
    metadata.source_url = source_url
    metadata.canonical_url = metadata.canonical_url or source_url
    if title := candidate.metadata.get("title"):
        metadata.title = title
    if author := candidate.metadata.get("author"):
        metadata.author = author
    if published_at := candidate.metadata.get("published_at"):
        metadata.published_at = published_at
    if modified_at := candidate.metadata.get("modified_at"):
        metadata.modified_at = modified_at
    return metadata



def structured_candidate_to_markdown(candidate: StructuredContentCandidate, renderer: MarkdownRenderer, base_url: str) -> str:
    if candidate.kind == ContentKind.MARKDOWN:
        return candidate.value if isinstance(candidate.value, str) and "```" in candidate.value else normalize_line_whitespace(str(candidate.value))
    if candidate.kind == ContentKind.HTML:
        return renderer.render_html(str(candidate.value), candidate.metadata.get("canonical_url") or candidate.metadata.get("source_url") or base_url)
    if candidate.kind == ContentKind.TEXT:
        return renderer.render_text(str(candidate.value))
    if candidate.kind == ContentKind.BLOCKS:
        return render_blocks(candidate.value if isinstance(candidate.value, list) else [], renderer)
    return renderer.render_text(str(candidate.value))



def render_blocks(blocks: list[Any], renderer: MarkdownRenderer) -> str:
    rendered: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type", "")).lower()
        if block_type in {"heading", "header"}:
            level = int(block.get("level") or 2)
            text = extract_text_from_block(block)
            if text:
                rendered.append(f"{'#' * max(1, min(level, 6))} {text}")
        elif block_type in {"paragraph", "text"}:
            text = extract_text_from_block(block)
            if text:
                rendered.append(text)
        elif block_type in {"code", "codeblock"}:
            language = str(block.get("language") or block.get("lang") or "")
            code = str(block.get("code") or block.get("text") or extract_text_from_block(block))
            rendered.append(f"```{language}\n{code.rstrip()}\n```")
        elif block_type in {"list", "bulletlist", "orderedlist"}:
            items = block.get("items") or block.get("children") or []
            ordered = block_type == "orderedlist" or bool(block.get("ordered"))
            lines = []
            for idx, item in enumerate(items, start=1):
                text = extract_text_from_block(item)
                if text:
                    marker = f"{idx}." if ordered else "-"
                    lines.append(f"{marker} {text}")
            if lines:
                rendered.append("\n".join(lines))
        elif block_type in {"blockquote", "quote"}:
            text = extract_text_from_block(block)
            if text:
                rendered.append("\n".join(f"> {line}" for line in text.splitlines()))
        else:
            text = extract_text_from_block(block)
            if text:
                rendered.append(text)
    return "\n\n".join(item.strip() for item in rendered if item.strip()).strip()



def extract_text_from_block(value: Any) -> str:
    if isinstance(value, str):
        return normalize_whitespace(value)
    if isinstance(value, dict):
        for key in ["text", "content", "value", "title", "name"]:
            if value.get(key):
                return normalize_whitespace(str(value[key]))
        if children := value.get("children"):
            if isinstance(children, list):
                parts = [extract_text_from_block(child) for child in children]
                return normalize_whitespace(" ".join(part for part in parts if part))
    if isinstance(value, list):
        parts = [extract_text_from_block(item) for item in value]
        return normalize_whitespace(" ".join(part for part in parts if part))
    return ""
