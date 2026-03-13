from __future__ import annotations

import re
from urllib.parse import urlparse

from ..models import CandidateKind, CandidateSource, FetchSnapshot, Scope
from ..utils.url import absolutize, markdown_twin_urls, same_host, same_section


MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
BARE_URL_RE = re.compile(r"(?P<url>https?://\S+|/\S+\.(?:md|markdown)\b|/\S+llms-full\.txt\b)")
TRAILING_URL_NOISE = ".,;:!?)]}\"'"


class LLMSDiscovery:
    def parse_snapshot(self, snapshot: FetchSnapshot, requested_url: str, scope: Scope) -> list[CandidateSource]:
        if not snapshot.text:
            return []
        lines = [line.strip() for line in snapshot.text.splitlines() if line.strip()]
        candidates: list[CandidateSource] = []
        in_fenced_code_block = False
        for line in lines:
            if line.startswith("```"):
                in_fenced_code_block = not in_fenced_code_block
                continue
            if in_fenced_code_block:
                continue
            for match in MARKDOWN_LINK_RE.finditer(line):
                href = self._safe_absolutize(snapshot.final_url or snapshot.url, match.group(2))
                if href is None:
                    continue
                candidate = self._candidate_for_url(href, requested_url, scope, evidence=["llms_markdown_link"])
                if candidate is not None:
                    candidates.append(candidate)
            for match in BARE_URL_RE.finditer(line):
                href = self._safe_absolutize(snapshot.final_url or snapshot.url, match.group("url"))
                if href is None:
                    continue
                candidate = self._candidate_for_url(href, requested_url, scope, evidence=["llms_bare_url"])
                if candidate is not None:
                    candidates.append(candidate)
        deduped = dedupe_candidates(candidates)
        deduped.sort(key=lambda item: item.confidence, reverse=True)
        return deduped

    def markdown_twin_candidates(self, requested_url: str) -> list[CandidateSource]:
        candidates = [
            CandidateSource(
                kind=CandidateKind.MARKDOWN_TWIN,
                url=url,
                method="GET",
                confidence=score_markdown_candidate(url, requested_url, Scope.PAGE, from_llms=False),
                cost=1,
                evidence=["heuristic_markdown_twin"],
            )
            for url in markdown_twin_urls(requested_url)
        ]
        return dedupe_candidates(candidates)

    def _safe_absolutize(self, base_url: str, maybe_relative: str) -> str | None:
        # llms-full documents can include JSON samples and punctuation-adjacent URLs.
        # Strip non-URL trailing delimiters and skip malformed tokens instead of crashing.
        cleaned = maybe_relative.strip().strip("<>").rstrip(TRAILING_URL_NOISE)
        if not cleaned:
            return None
        try:
            return absolutize(base_url, cleaned)
        except ValueError:
            return None

    def _candidate_for_url(self, href: str, requested_url: str, scope: Scope, evidence: list[str]) -> CandidateSource | None:
        if href.endswith((".md", ".markdown")):
            kind = CandidateKind.LINKED_MARKDOWN
        elif href.endswith("llms-full.txt"):
            kind = CandidateKind.LLMS_FULL
        elif href.endswith("llms.txt"):
            kind = CandidateKind.LLMS_TXT
        else:
            return None
        confidence = score_markdown_candidate(href, requested_url, scope, from_llms=True)
        return CandidateSource(
            kind=kind,
            url=href,
            method="GET",
            confidence=confidence,
            cost=0,
            evidence=evidence,
        )



def score_markdown_candidate(candidate_url: str, requested_url: str, scope: Scope, from_llms: bool) -> float:
    score = 0.15
    candidate_path = urlparse(candidate_url).path
    requested_path = urlparse(requested_url).path
    if candidate_path.endswith((".md", ".markdown")):
        score += 0.25
    if from_llms:
        score += 0.2
    candidate_base = strip_markdown_suffix(candidate_path)
    requested_base = requested_path.rstrip("/") or "/"
    if candidate_base == requested_base:
        score += 0.3
    if same_section(requested_url, candidate_url):
        score += 0.15
    if scope != Scope.PAGE and candidate_url.endswith("llms-full.txt"):
        score += 0.2
    elif scope == Scope.PAGE and candidate_url.endswith("llms-full.txt"):
        score += 0.05
    if same_host(candidate_url, requested_url):
        score += 0.05
    return min(score, 0.99)



def dedupe_candidates(candidates: list[CandidateSource]) -> list[CandidateSource]:
    deduped: dict[tuple[str | None, str, str], CandidateSource] = {}
    for candidate in candidates:
        key = (candidate.url, candidate.method, candidate.kind.value)
        current = deduped.get(key)
        if current is None or candidate.confidence > current.confidence:
            deduped[key] = candidate
    return list(deduped.values())



def strip_markdown_suffix(path: str) -> str:
    for suffix in (".markdown", ".md"):
        if path.endswith(suffix):
            stripped = path[: -len(suffix)]
            return stripped or "/"
    return path or "/"
