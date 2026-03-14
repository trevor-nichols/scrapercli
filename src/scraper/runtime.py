from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import ScraperConfig
from .discovery.probes import DiscoveryEngine
from .discovery.sitemap import SitemapDiscovery
from .extractors.browser import BrowserDOMExtractor, BrowserDiscoveryExtractor, BrowserExplorer
from .extractors.html_static import StaticHTMLExtractor
from .extractors.http_replay import HTTPReplayExtractor
from .extractors.publisher_markdown import PublisherMarkdownExtractor
from .extractors.structured import StructuredDataExtractor
from .html.markdown import MarkdownDocumentBuilder, MarkdownRenderer
from .html.repetition import RepetitionIndex
from .http.client import HttpClient
from .models import OutputProfile
from .observability.recorder import DecisionRecorder
from .observability.store import ArtifactPersistencePolicy, ArtifactStore
from .pipeline.crawler import Crawler
from .pipeline.orchestrator import ScrapeOrchestrator
from .pipeline.quality import QualityAssessor


@dataclass
class Runtime:
    config: ScraperConfig
    artifacts: ArtifactStore
    recorder: DecisionRecorder
    http_client: HttpClient
    repetition_index: RepetitionIndex
    discovery: DiscoveryEngine
    orchestrator: ScrapeOrchestrator
    crawler: Crawler

    def close(self) -> None:
        self.http_client.close()


class RuntimeFactory:
    @staticmethod
    def _artifact_policy(config: ScraperConfig) -> ArtifactPersistencePolicy:
        if config.output.profile == OutputProfile.VERBOSE:
            return ArtifactPersistencePolicy.verbose(
                save_raw_sources=config.output.raw_sources,
                save_metadata_sidecar=config.output.metadata_sidecar,
            )
        return ArtifactPersistencePolicy.minimal()

    @staticmethod
    def build(config: ScraperConfig, *, output_root: Path | None = None) -> Runtime:
        if output_root is not None:
            config = config.model_copy(deep=True)
            config.output.root_dir = output_root

        artifacts = ArtifactStore(config.output.root_dir, policy=RuntimeFactory._artifact_policy(config))
        recorder = DecisionRecorder(artifacts.decisions_path)
        http_client = HttpClient(config, artifacts, recorder)
        repetition_index = RepetitionIndex(artifacts.repetition_store_path)
        discovery = DiscoveryEngine(http_client, recorder)
        include_frontmatter = config.output.frontmatter

        publisher_markdown = PublisherMarkdownExtractor(
            http_client,
            recorder,
            include_frontmatter=include_frontmatter,
        )
        structured = StructuredDataExtractor(recorder, include_frontmatter=include_frontmatter)
        static_html = StaticHTMLExtractor(
            recorder,
            repetition_index,
            include_frontmatter=include_frontmatter,
        )
        http_replay = HTTPReplayExtractor(
            http_client,
            recorder,
            include_frontmatter=include_frontmatter,
        )
        browser_discovery = None
        browser_dom = None
        if config.browser.enabled:
            explorer = BrowserExplorer(
                recorder=recorder,
                timeout_ms=config.browser.timeout_ms,
                wait_until=config.browser.wait_until,
                auto_interact=config.browser.auto_interact,
                max_auto_clicks=config.browser.max_auto_clicks,
                headless=config.browser.headless,
            )
            browser_discovery = BrowserDiscoveryExtractor(explorer, recorder)
            browser_dom = BrowserDOMExtractor(
                explorer,
                recorder,
                repetition_index,
                include_frontmatter=include_frontmatter,
            )

        quality = QualityAssessor(config.quality)
        orchestrator = ScrapeOrchestrator(
            discovery=discovery,
            publisher_markdown=publisher_markdown,
            structured=structured,
            static_html=static_html,
            http_replay=http_replay,
            browser_discovery=browser_discovery,
            browser_dom=browser_dom,
            quality=quality,
            recorder=recorder,
            artifacts=artifacts,
            repetition_index=repetition_index,
        )
        crawler = Crawler(orchestrator, SitemapDiscovery(http_client, recorder))
        return Runtime(
            config=config,
            artifacts=artifacts,
            recorder=recorder,
            http_client=http_client,
            repetition_index=repetition_index,
            discovery=discovery,
            orchestrator=orchestrator,
            crawler=crawler,
        )
