from __future__ import annotations

from typing import Iterable

from ..discovery.probes import DiscoveryEngine
from ..extractors.browser import BrowserDOMExtractor, BrowserDiscoveryExtractor
from ..models import BrowserDiscoveryResult
from ..extractors.html_static import StaticHTMLExtractor
from ..extractors.http_replay import HTTPReplayExtractor
from ..extractors.publisher_markdown import PublisherMarkdownExtractor
from ..extractors.structured import StructuredDataExtractor
from ..html.repetition import RepetitionIndex
from ..models import CandidateSource, DiscoveryBundle, DocumentResult, ExtractionAttempt, ExtractionMode, Scope
from ..observability.recorder import DecisionRecorder
from ..observability.store import ArtifactStore
from .quality import QualityAssessor


class ScrapeOrchestrator:
    def __init__(
        self,
        *,
        discovery: DiscoveryEngine,
        publisher_markdown: PublisherMarkdownExtractor,
        structured: StructuredDataExtractor,
        static_html: StaticHTMLExtractor,
        http_replay: HTTPReplayExtractor,
        browser_discovery: BrowserDiscoveryExtractor | None,
        browser_dom: BrowserDOMExtractor | None,
        quality: QualityAssessor,
        recorder: DecisionRecorder,
        artifacts: ArtifactStore,
        repetition_index: RepetitionIndex,
    ) -> None:
        self.discovery_engine = discovery
        self.publisher_markdown = publisher_markdown
        self.structured = structured
        self.static_html = static_html
        self.http_replay = http_replay
        self.browser_discovery = browser_discovery
        self.browser_dom = browser_dom
        self.quality = quality
        self.recorder = recorder
        self.artifacts = artifacts
        self.repetition_index = repetition_index

    def scrape(self, url: str, scope: Scope = Scope.PAGE) -> DocumentResult:
        bundle = self.discovery_engine.discover(url, scope)
        result = DocumentResult(requested_url=url, normalized_url=bundle.normalized_url, scope=scope, decisions_path=self.artifacts.decisions_path, raw_bundle_dir=self.artifacts.root_dir)
        best_attempt: ExtractionAttempt | None = None
        best_quality_rank = -1
        if bundle.page is not None:
            result.final_url = bundle.page.final_url
        if "robots_disallow" in bundle.signals:
            result.errors.append("Blocked by robots.txt")
            return result

        def consider(attempt: ExtractionAttempt) -> None:
            nonlocal best_attempt, best_quality_rank
            result.attempts.append(attempt)
            self.recorder.record(
                "extraction",
                bundle.normalized_url,
                "attempt_finished",
                {
                    "mode": attempt.mode.value,
                    "success": attempt.success,
                    "outcome": attempt.outcome,
                    "quality": attempt.quality.model_dump(mode="python") if attempt.quality else None,
                },
            )
            if attempt.document and attempt.quality:
                rank = (1000 if attempt.quality.passed else 0) + attempt.quality.body_chars
                if rank > best_quality_rank:
                    best_quality_rank = rank
                    best_attempt = attempt

        # 1. Publisher markdown
        attempt = self.publisher_markdown.run(bundle)
        if attempt.document:
            attempt.quality = self.quality.assess(attempt.document, attempt.mode)
        consider(attempt)
        if attempt.document and attempt.quality and attempt.quality.passed:
            return self._finalize(result, bundle, attempt)
        self._record_next_step(bundle, attempt, ExtractionMode.STRUCTURED_HTTP, "publisher_markdown_failed_or_low_quality")

        # 2. Structured inline data
        attempt = self.structured.run(bundle)
        if attempt.document:
            attempt.quality = self.quality.assess(attempt.document, attempt.mode)
        consider(attempt)
        if attempt.document and attempt.quality and attempt.quality.passed:
            return self._finalize(result, bundle, attempt)
        self._record_next_step(bundle, attempt, ExtractionMode.STATIC_HTML, "structured_http_failed_or_low_quality")

        # 3. Static HTML
        attempt = self.static_html.run(bundle)
        if attempt.document:
            attempt.quality = self.quality.assess(attempt.document, attempt.mode)
        consider(attempt)
        if attempt.document and attempt.quality and attempt.quality.passed:
            return self._finalize(result, bundle, attempt)

        # 4. HTTP replay if signals suggest it may help
        if self._should_attempt_http_replay(bundle):
            self._record_next_step(bundle, attempt, ExtractionMode.HTTP_REPLAY, "static_html_failed_or_shell_detected")
            attempt = self.http_replay.run(bundle)
            if attempt.document:
                attempt.quality = self.quality.assess(attempt.document, attempt.mode)
            consider(attempt)
            if attempt.document and attempt.quality and attempt.quality.passed:
                return self._finalize(result, bundle, attempt)

        # 5. Browser-assisted discovery
        browser_result: BrowserDiscoveryResult | None = None
        if self.browser_discovery is not None:
            self._record_next_step(bundle, attempt, ExtractionMode.BROWSER_DISCOVERY, "http_only_paths_failed")
            attempt = self.browser_discovery.run(bundle)
            if attempt.success and attempt.extra:
                browser_result = BrowserDiscoveryResult.model_validate(attempt.extra)
                bundle.candidates.extend(browser_result.candidate_sources)
                bundle.signals.extend(browser_result.signals)
            consider(attempt)
            if browser_result and browser_result.candidate_sources:
                self._record_next_step(bundle, attempt, ExtractionMode.HTTP_REPLAY, "browser_discovery_found_replayable_requests")
                attempt = self.http_replay.run(bundle)
                if attempt.document:
                    attempt.quality = self.quality.assess(attempt.document, attempt.mode)
                consider(attempt)
                if attempt.document and attempt.quality and attempt.quality.passed:
                    return self._finalize(result, bundle, attempt)

        # 6. Browser DOM fallback
        if self.browser_dom is not None:
            self._record_next_step(bundle, attempt, ExtractionMode.BROWSER_DOM, "browser_discovery_not_replayable_or_quality_failed")
            attempt = self.browser_dom.run(bundle, discovery_result=browser_result)
            if attempt.document:
                attempt.quality = self.quality.assess(attempt.document, attempt.mode)
            consider(attempt)
            if attempt.document and attempt.quality and attempt.quality.passed:
                return self._finalize(result, bundle, attempt)

        if best_attempt is not None:
            result.document = best_attempt.document
            result.success = bool(best_attempt.quality and best_attempt.quality.passed)
            if best_attempt.document:
                result.markdown_path = self.artifacts.save_markdown(best_attempt.url, best_attempt.document.markdown)
                result.metadata_path = self.artifacts.save_metadata(best_attempt.url, best_attempt.document.metadata.model_dump(mode="python"))
            if not result.success:
                result.errors.append("All extraction paths completed, but quality threshold was not met")
        if bundle.page and bundle.page.text and bundle.page.is_html:
            self.repetition_index.update_from_html(bundle.page.final_url, bundle.page.text)
        return result

    def _should_attempt_http_replay(self, bundle: DiscoveryBundle) -> bool:
        if any(candidate.kind.value in {"api_endpoint", "graphql_endpoint", "browser_captured_endpoint"} for candidate in bundle.candidates):
            return True
        if "thin_html_shell" in bundle.signals or "api_urls_discoverable" in bundle.signals:
            return True
        return False

    def _record_next_step(self, bundle: DiscoveryBundle, previous_attempt: ExtractionAttempt, next_mode: ExtractionMode, trigger: str) -> None:
        self.recorder.record_escalation(
            url=bundle.normalized_url,
            previous_mode=previous_attempt.mode.value,
            trigger_condition=trigger,
            observed_signals=previous_attempt.observed_signals + (previous_attempt.quality.reasons if previous_attempt.quality else []),
            next_mode=next_mode.value,
        )

    def _finalize(self, result: DocumentResult, bundle: DiscoveryBundle, attempt: ExtractionAttempt) -> DocumentResult:
        result.document = attempt.document
        result.success = True
        if attempt.document:
            result.markdown_path = self.artifacts.save_markdown(bundle.normalized_url, attempt.document.markdown)
            result.metadata_path = self.artifacts.save_metadata(bundle.normalized_url, attempt.document.metadata.model_dump(mode="python"))
        if bundle.page and bundle.page.text and bundle.page.is_html:
            self.repetition_index.update_from_html(bundle.page.final_url, bundle.page.text)
        return result
