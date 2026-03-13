from __future__ import annotations

import json
import time
from typing import Any

from ..adapters import AdapterRegistry
from ..html.markdown import MarkdownDocumentBuilder, MarkdownRenderer
from ..html.repetition import RepetitionIndex
from ..html.scoring import HTMLScorer
from ..models import (
    BrowserCapturedRequest,
    BrowserDiscoveryResult,
    CandidateKind,
    CandidateSource,
    ContentKind,
    DiscoveryBundle,
    ExtractionAttempt,
    ExtractionMode,
    MarkdownDocument,
    PageMetadata,
)
from ..observability.recorder import DecisionRecorder
from .html_static import prepare_html_for_scoring, render_selected_nodes


class BrowserUnavailableError(RuntimeError):
    pass


class BrowserExplorer:
    def __init__(self, recorder: DecisionRecorder, timeout_ms: int, wait_until: str, auto_interact: bool, max_auto_clicks: int, headless: bool = True) -> None:
        self.recorder = recorder
        self.timeout_ms = timeout_ms
        self.wait_until = wait_until
        self.auto_interact = auto_interact
        self.max_auto_clicks = max_auto_clicks
        self.headless = headless

    def discover(self, url: str) -> BrowserDiscoveryResult:
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # pragma: no cover - import error path
            raise BrowserUnavailableError(str(exc)) from exc

        captured: list[BrowserCapturedRequest] = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context()
            page = context.new_page()

            def on_response(response):
                try:
                    request = response.request
                    resource_type = request.resource_type
                    headers = {str(k): str(v) for k, v in request.headers.items()}
                    response_headers = {str(k): str(v) for k, v in response.headers.items()}
                    response_body = None
                    content_type = response_headers.get("content-type", "")
                    if resource_type in {"xhr", "fetch"} or "json" in content_type or "graphql" in request.url:
                        try:
                            body_text = response.text()
                            response_body = body_text[:200_000]
                        except Exception:
                            response_body = None
                    captured.append(
                        BrowserCapturedRequest(
                            url=request.url,
                            method=request.method,
                            headers=headers,
                            post_data=request.post_data,
                            resource_type=resource_type,
                            response_status=response.status,
                            response_headers=response_headers,
                            response_body=response_body,
                        )
                    )
                except Exception:
                    return

            page.on("response", on_response)
            try:
                page.goto(url, wait_until=self.wait_until, timeout=self.timeout_ms)
                if self.auto_interact:
                    self._auto_interact(page)
                page.wait_for_timeout(750)
                dom_html = page.content()
            except PlaywrightError as exc:
                browser.close()
                raise BrowserUnavailableError(str(exc)) from exc
            browser.close()
        result = BrowserDiscoveryResult(dom_html=dom_html, requests=captured)
        result.candidate_sources = self._candidate_sources_from_requests(captured)
        if result.candidate_sources:
            result.signals.append("browser_captured_replayable_requests")
        if dom_html and len(dom_html) > 0:
            result.signals.append("browser_rendered_dom_available")
        return result

    def _auto_interact(self, page) -> None:
        selectors = [
            "[role=tab]",
            "button[aria-expanded='false']",
            "button:has-text('Load more')",
            "button:has-text('Show more')",
            "button:has-text('Read more')",
            "button:has-text('Expand')",
        ]
        clicks = 0
        for selector in selectors:
            if clicks >= self.max_auto_clicks:
                break
            locator = page.locator(selector)
            count = min(locator.count(), self.max_auto_clicks - clicks)
            for index in range(count):
                try:
                    target = locator.nth(index)
                    if target.is_visible():
                        target.click(timeout=1000)
                        page.wait_for_timeout(250)
                        clicks += 1
                except Exception:
                    continue

    def _candidate_sources_from_requests(self, requests: list[BrowserCapturedRequest]) -> list[CandidateSource]:
        candidates: list[CandidateSource] = []
        for request in requests:
            url = request.url
            content_type = request.response_headers.get("content-type", "") if request.response_headers else ""
            if not (url.endswith(".json") or "json" in content_type or "graphql" in url or "/api/" in url or "/data/" in url):
                continue
            payload = None
            if request.response_body:
                try:
                    payload = json.loads(request.response_body)
                except json.JSONDecodeError:
                    payload = None
            kind = CandidateKind.BROWSER_CAPTURED_ENDPOINT
            candidates.append(
                CandidateSource(
                    kind=kind,
                    url=url,
                    method=request.method,
                    headers=filter_replay_headers(request.headers),
                    body=request.post_data,
                    payload=payload,
                    confidence=0.88 if payload is not None else 0.72,
                    cost=5,
                    evidence=["browser_network_capture", f"resource_type:{request.resource_type or 'unknown'}"],
                    metadata={"response_status": request.response_status},
                )
            )
        deduped: dict[tuple[str, str, str | None], CandidateSource] = {}
        for candidate in candidates:
            key = (candidate.url or "", candidate.method, candidate.body)
            current = deduped.get(key)
            if current is None or candidate.confidence > current.confidence:
                deduped[key] = candidate
        return list(deduped.values())


class BrowserDiscoveryExtractor:
    mode_name = ExtractionMode.BROWSER_DISCOVERY

    def __init__(self, explorer: BrowserExplorer, recorder: DecisionRecorder) -> None:
        self.explorer = explorer
        self.recorder = recorder

    def run(self, bundle: DiscoveryBundle) -> ExtractionAttempt:
        start = time.perf_counter()
        attempt = ExtractionAttempt(mode=self.mode_name, url=bundle.normalized_url)
        try:
            result = self.explorer.discover(bundle.normalized_url)
        except BrowserUnavailableError as exc:
            attempt.outcome = "browser_unavailable"
            attempt.observed_signals.append("browser_unavailable")
            attempt.extra = {"error": str(exc)}
            attempt.elapsed_ms = int((time.perf_counter() - start) * 1000)
            return attempt
        attempt.success = bool(result.candidate_sources or result.dom_html)
        attempt.outcome = "browser_discovery_completed" if attempt.success else "browser_discovery_empty"
        attempt.observed_signals.extend(result.signals)
        attempt.extra = result.model_dump(mode="python")
        attempt.elapsed_ms = int((time.perf_counter() - start) * 1000)
        return attempt


class BrowserDOMExtractor:
    mode_name = ExtractionMode.BROWSER_DOM

    def __init__(self, explorer: BrowserExplorer, recorder: DecisionRecorder, repetition_index: RepetitionIndex, include_frontmatter: bool = True) -> None:
        self.explorer = explorer
        self.recorder = recorder
        self.repetition_index = repetition_index
        self.scorer = HTMLScorer(repetition_index)
        self.renderer = MarkdownRenderer()
        self.builder = MarkdownDocumentBuilder(self.renderer, include_frontmatter=include_frontmatter)
        self.adapters = AdapterRegistry()

    def run(self, bundle: DiscoveryBundle, discovery_result: BrowserDiscoveryResult | None = None) -> ExtractionAttempt:
        start = time.perf_counter()
        attempt = ExtractionAttempt(mode=self.mode_name, url=bundle.normalized_url)
        result = discovery_result
        if result is None or not result.dom_html:
            try:
                result = self.explorer.discover(bundle.normalized_url)
            except BrowserUnavailableError as exc:
                attempt.outcome = "browser_unavailable"
                attempt.observed_signals.append("browser_unavailable")
                attempt.extra = {"error": str(exc)}
                attempt.elapsed_ms = int((time.perf_counter() - start) * 1000)
                return attempt
        dom_html = result.dom_html or ""
        adapter = self.adapters.for_framework(bundle.framework_hint.framework_family)
        prepared_html = prepare_html_for_scoring(adapter.preprocess_html(dom_html))
        scored_nodes, diagnostics = self.scorer.score(bundle.normalized_url, prepared_html, title=bundle.metadata.title if bundle.metadata else None)
        winner = self.scorer.choose_winner(scored_nodes)
        if winner is None:
            attempt.outcome = "browser_dom_no_winner"
            attempt.observed_signals.append("browser_dom_scoring_failed")
            attempt.elapsed_ms = int((time.perf_counter() - start) * 1000)
            return attempt
        rendered_html = render_selected_nodes(prepared_html, winner, scored_nodes, self.scorer)
        metadata = bundle.metadata.model_copy(deep=True) if bundle.metadata else PageMetadata(source_url=bundle.normalized_url, canonical_url=bundle.normalized_url)
        markdown_body = self.renderer.render_html(rendered_html, metadata.canonical_url or bundle.normalized_url)
        markdown = self.builder.build(metadata, markdown_body, extra_frontmatter={"extraction_method": self.mode_name.value, "source_kind": CandidateKind.BROWSER_DOM.value, "body_score": f"{diagnostics.body_score:.2f}", "chrome_score": f"{diagnostics.chrome_score:.2f}"})
        attempt.success = True
        attempt.document = MarkdownDocument(markdown=markdown, metadata=metadata, content_kind=ContentKind.HTML, source_kind=CandidateKind.BROWSER_DOM, diagnostics={"winner_xpath": diagnostics.winner_xpath, "body_score": diagnostics.body_score, "chrome_score": diagnostics.chrome_score, "metadata_preserve_score": diagnostics.metadata_preserve_score, "body_chars": diagnostics.body_chars, "signals": diagnostics.signals, "browser_requests": len(result.requests)})
        attempt.outcome = "browser_dom_selected"
        attempt.observed_signals.extend(result.signals)
        attempt.elapsed_ms = int((time.perf_counter() - start) * 1000)
        return attempt



def filter_replay_headers(headers: dict[str, str]) -> dict[str, str]:
    allow = {"accept", "content-type", "authorization", "x-api-key", "x-requested-with"}
    return {key: value for key, value in headers.items() if key.lower() in allow}
