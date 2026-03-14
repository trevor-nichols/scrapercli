from pathlib import Path

from scraper.extractors.html_static import StaticHTMLExtractor
from scraper.html.repetition import RepetitionIndex
from scraper.models import DiscoveryBundle, FetchSnapshot, Scope
from scraper.models import QualityThresholds
from scraper.observability.recorder import DecisionRecorder
from scraper.observability.store import ArtifactPersistencePolicy, ArtifactStore
from scraper.pipeline.orchestrator import ScrapeOrchestrator
from scraper.pipeline.quality import QualityAssessor


class NullExtractor:
    mode_name = "null"

    def run(self, bundle):
        from scraper.models import ExtractionAttempt, ExtractionMode

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


def test_orchestrator_minimal_profile_saves_only_markdown(tmp_path) -> None:
    html = Path("tests/fixtures/article_page.html").read_text(encoding="utf-8")
    artifacts = ArtifactStore(tmp_path / "out", policy=ArtifactPersistencePolicy.minimal())
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
    assert result.markdown_path is not None and result.markdown_path.exists()
    assert result.metadata_path is None
    assert result.decisions_path is None
