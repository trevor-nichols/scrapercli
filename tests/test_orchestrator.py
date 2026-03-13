from pathlib import Path

from staged_scraper.extractors.html_static import StaticHTMLExtractor
from staged_scraper.extractors.publisher_markdown import PublisherMarkdownExtractor
from staged_scraper.extractors.structured import StructuredDataExtractor
from staged_scraper.html.repetition import RepetitionIndex
from staged_scraper.models import DiscoveryBundle, FetchSnapshot, Scope
from staged_scraper.observability.recorder import DecisionRecorder
from staged_scraper.observability.store import ArtifactStore
from staged_scraper.pipeline.orchestrator import ScrapeOrchestrator
from staged_scraper.pipeline.quality import QualityAssessor
from staged_scraper.models import QualityThresholds


class NullExtractor:
    mode_name = "null"

    def run(self, bundle):
        from staged_scraper.models import ExtractionAttempt, ExtractionMode

        mapping = {
            "publisher": ExtractionMode.PUBLISHER_MARKDOWN,
            "structured": ExtractionMode.STRUCTURED_HTTP,
            "replay": ExtractionMode.HTTP_REPLAY,
        }
        return ExtractionAttempt(mode=mapping[self.mode_name], url=bundle.normalized_url, outcome="empty")


class StubDiscovery:
    def __init__(self, bundle: DiscoveryBundle) -> None:
        self.bundle = bundle

    def discover(self, url: str, scope: Scope) -> DiscoveryBundle:
        return self.bundle


class PublisherEmpty(NullExtractor):
    mode_name = "publisher"


class StructuredEmpty(NullExtractor):
    mode_name = "structured"


class ReplayEmpty(NullExtractor):
    mode_name = "replay"


def test_orchestrator_escalates_to_static_html_and_records_decisions(tmp_path) -> None:
    html = Path("tests/fixtures/article_page.html").read_text(encoding="utf-8")
    artifacts = ArtifactStore(tmp_path / "out")
    recorder = DecisionRecorder(artifacts.decisions_path)
    repetition = RepetitionIndex(artifacts.repetition_store_path)
    page = FetchSnapshot(
        url="https://example.com/blog/example-article",
        final_url="https://example.com/blog/example-article",
        method="GET",
        status_code=200,
        headers={"content-type": "text/html; charset=utf-8"},
        content_type="text/html; charset=utf-8",
        text=html,
    )
    bundle = DiscoveryBundle(
        requested_url=page.url,
        normalized_url=page.url,
        scope=Scope.PAGE,
        page=page,
    )
    orchestrator = ScrapeOrchestrator(
        discovery=StubDiscovery(bundle),
        publisher_markdown=PublisherEmpty(),
        structured=StructuredEmpty(),
        static_html=StaticHTMLExtractor(recorder, repetition),
        http_replay=ReplayEmpty(),
        browser_discovery=None,
        browser_dom=None,
        quality=QualityAssessor(QualityThresholds()),
        recorder=recorder,
        artifacts=artifacts,
        repetition_index=repetition,
    )

    result = orchestrator.scrape(page.url, Scope.PAGE)

    assert result.success
    assert result.document is not None
    decisions = artifacts.decisions_path.read_text(encoding="utf-8")
    assert '"stage":"escalation"' in decisions
    assert 'static_html' in decisions
