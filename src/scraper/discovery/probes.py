from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup

from ..adapters import AdapterRegistry
from ..html.metadata import MetadataExtractor
from ..http.client import HttpClient
from ..http.robots import RobotsPolicy
from ..models import CandidateKind, CandidateSource, DiscoveryBundle, PageMetadata, Scope
from ..observability.recorder import DecisionRecorder
from ..utils.url import absolutize, llms_probe_urls, normalize_url, site_root
from .framework import FrameworkDetectorRegistry
from .llms import LLMSDiscovery, dedupe_candidates


JSON_URL_RE = re.compile(r"(?:\"|')(?P<url>(?:https?://|/)[^\"']+?\.json(?:\?[^\"']*)?)(?:\"|')")
API_URL_RE = re.compile(r"(?:\"|')(?P<url>(?:https?://|/)(?:api|content|data)/[^\"']+?)(?:\"|')")
GRAPHQL_RE = re.compile(r"(?:\"|')(?P<url>(?:https?://|/)[^\"']*graphql[^\"']*)(?:\"|')", re.I)
ASSIGNMENT_MARKERS = ["__INITIAL_STATE__", "__NUXT__", "__APOLLO_STATE__", "__PRELOADED_STATE__"]


class DiscoveryEngine:
    def __init__(self, http_client: HttpClient, recorder: DecisionRecorder) -> None:
        self.http_client = http_client
        self.recorder = recorder
        self.llms = LLMSDiscovery()
        self.framework_detectors = FrameworkDetectorRegistry()
        self.metadata_extractor = MetadataExtractor()
        self.robots_policy = RobotsPolicy(http_client.config.user_agent)
        self.adapters = AdapterRegistry()

    def discover(self, url: str, scope: Scope) -> DiscoveryBundle:
        normalized = normalize_url(url)
        bundle = DiscoveryBundle(requested_url=url, normalized_url=normalized, scope=scope)
        bundle.robots = self._fetch_robots(normalized)
        if bundle.robots:
            bundle.sitemap_urls.extend(bundle.robots.sitemaps)
        if self.http_client.config.crawl.respect_robots and bundle.robots and not self.robots_policy.can_fetch(normalized):
            bundle.signals.append("robots_disallow")
            self.recorder.record("discovery", normalized, "robots_disallow", {"robots_url": bundle.robots.url}, level="warning")
            return bundle

        for probe_url in llms_probe_urls(normalized):
            snapshot = self.http_client.fetch(probe_url, allow_status={404})
            if snapshot.status_code == 200 and snapshot.text:
                bundle.llms_snapshots.append(snapshot)
                bundle.candidates.extend(self.llms.parse_snapshot(snapshot, normalized, scope))
                self.recorder.record("discovery", normalized, "llms_probe_hit", {"probe_url": probe_url, "status_code": snapshot.status_code})
            else:
                self.recorder.record("discovery", normalized, "llms_probe_miss", {"probe_url": probe_url, "status_code": snapshot.status_code})

        page = self.http_client.fetch(normalized, conditional=True, allow_status={401, 403, 404})
        bundle.page = page
        if page.status_code in {401, 403}:
            bundle.signals.append("auth_required")
        if page.text and page.is_html:
            bundle.metadata = self.metadata_extractor.extract(page.text, page.final_url)
            bundle.framework_hint = self.framework_detectors.detect(page.text, page.final_url)
            bundle.candidates.extend(self.llms.markdown_twin_candidates(normalized))
            bundle.candidates.extend(extract_inline_structured_candidates(page.text, page.final_url))
            bundle.candidates.append(CandidateSource(kind=CandidateKind.HTML_PAGE, url=page.final_url, method="GET", confidence=0.55, cost=2, evidence=["fetched_target_html"]))
            adapter = self.adapters.for_framework(bundle.framework_hint.framework_family)
            bundle.candidates.extend(adapter.augment_candidates(bundle))
            if is_thin_html_shell(page.text):
                bundle.signals.append("thin_html_shell")
            if any(candidate.kind in {CandidateKind.JSON_LD, CandidateKind.HYDRATION, CandidateKind.INLINE_STATE} for candidate in bundle.candidates):
                bundle.signals.append("inline_structured_data_present")
            if any(candidate.kind in {CandidateKind.API_ENDPOINT, CandidateKind.GRAPHQL_ENDPOINT} for candidate in bundle.candidates):
                bundle.signals.append("api_urls_discoverable")
        elif page.text and page.is_json:
            payload = parse_json_safe(page.text)
            if payload is not None:
                bundle.candidates.append(CandidateSource(kind=CandidateKind.API_ENDPOINT, url=page.final_url, method="GET", confidence=0.75, cost=1, payload=payload, evidence=["target_page_is_json"]))
            bundle.metadata = PageMetadata(source_url=page.final_url, canonical_url=page.final_url, content_type=page.content_type)
        bundle.candidates = rank_candidates(dedupe_candidates(bundle.candidates), normalized)
        return bundle

    def _fetch_robots(self, url: str):
        robots_url = site_root(url).rstrip("/") + "/robots.txt"
        snapshot = self.http_client.fetch(robots_url, allow_status={404})
        if snapshot.status_code != 200 or not snapshot.text:
            return None
        info = self.robots_policy.register(snapshot)
        self.recorder.record("discovery", url, "robots_fetched", {"robots_url": robots_url, "sitemaps": info.sitemaps})
        return info



def extract_inline_structured_candidates(html: str, base_url: str) -> list[CandidateSource]:
    candidates: list[CandidateSource] = []
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        text = tag.string or tag.get_text(strip=True)
        if not text:
            continue
        payload = parse_json_safe(text)
        if payload is not None:
            candidates.append(CandidateSource(kind=CandidateKind.JSON_LD, payload=payload, confidence=0.78, cost=0, evidence=["application/ld+json"]))
    next_data = soup.find(id="__NEXT_DATA__")
    if next_data and next_data.get_text(strip=True):
        payload = parse_json_safe(next_data.get_text(strip=True))
        if payload is not None:
            candidates.append(CandidateSource(kind=CandidateKind.HYDRATION, payload=payload, confidence=0.82, cost=0, evidence=["__NEXT_DATA__"]))
    for script in soup.find_all("script"):
        text = script.string or script.get_text(strip=False)
        if not text:
            continue
        for marker in ASSIGNMENT_MARKERS:
            if marker in text:
                payload = parse_assigned_json(text, marker)
                if payload is not None:
                    candidates.append(CandidateSource(kind=CandidateKind.INLINE_STATE, payload=payload, confidence=0.74, cost=0, evidence=[f"inline_state:{marker}"]))
        for match in JSON_URL_RE.finditer(text):
            url = absolutize(base_url, match.group("url"))
            candidates.append(CandidateSource(kind=CandidateKind.API_ENDPOINT, url=url, confidence=0.62, cost=2, evidence=["json_url_in_script"]))
        for match in API_URL_RE.finditer(text):
            url = absolutize(base_url, match.group("url"))
            candidates.append(CandidateSource(kind=CandidateKind.API_ENDPOINT, url=url, confidence=0.58, cost=2, evidence=["api_url_in_script"]))
        for match in GRAPHQL_RE.finditer(text):
            url = absolutize(base_url, match.group("url"))
            candidates.append(CandidateSource(kind=CandidateKind.GRAPHQL_ENDPOINT, url=url, confidence=0.56, cost=3, evidence=["graphql_url_in_script"]))
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if href.endswith((".md", ".markdown", "llms-full.txt")):
            candidates.append(CandidateSource(kind=CandidateKind.LINKED_MARKDOWN if href.endswith((".md", ".markdown")) else CandidateKind.LLMS_FULL, url=absolutize(base_url, href), confidence=0.6, cost=1, evidence=["page_linked_markdown"]))
    return dedupe_candidates(candidates)



def parse_json_safe(text: str) -> Any | None:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None



def parse_assigned_json(script_text: str, marker: str) -> Any | None:
    pattern = re.compile(re.escape(marker) + r"\s*=\s*", re.M)
    match = pattern.search(script_text)
    if not match:
        return None
    start = match.end()
    while start < len(script_text) and script_text[start].isspace():
        start += 1
    if start >= len(script_text):
        return None
    opening = script_text[start]
    if opening not in "[{":
        return None
    closing = "]" if opening == "[" else "}"
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(script_text)):
        ch = script_text[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == opening:
            depth += 1
        elif ch == closing:
            depth -= 1
            if depth == 0:
                snippet = script_text[start : idx + 1]
                return parse_json_safe(snippet)
    return None



def is_thin_html_shell(html: str) -> bool:
    soup = BeautifulSoup(html, "lxml")
    body = soup.body
    if body is None:
        return True
    text = body.get_text(" ", strip=True)
    script_count = len(soup.find_all("script"))
    return len(text) < 300 and script_count >= 8



def rank_candidates(candidates: list[CandidateSource], requested_url: str) -> list[CandidateSource]:
    priority = {
        CandidateKind.LINKED_MARKDOWN: 0,
        CandidateKind.LLMS_FULL: 1,
        CandidateKind.MARKDOWN_TWIN: 2,
        CandidateKind.JSON_LD: 3,
        CandidateKind.HYDRATION: 4,
        CandidateKind.INLINE_STATE: 5,
        CandidateKind.HTML_PAGE: 6,
        CandidateKind.API_ENDPOINT: 7,
        CandidateKind.GRAPHQL_ENDPOINT: 8,
        CandidateKind.BROWSER_CAPTURED_ENDPOINT: 9,
        CandidateKind.BROWSER_DOM: 10,
    }
    candidates.sort(key=lambda item: (priority.get(item.kind, 99), -item.confidence, item.cost, (item.url or requested_url)))
    return candidates
