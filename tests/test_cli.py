from typer.testing import CliRunner

from scraper.cli import _build_config, app
from scraper.models import CandidateKind, CandidateSource, CrawlManifest, CrawlManifestEntry, DiscoveryBundle, DocumentResult, ExtractionAttempt, ExtractionMode, OutputProfile, Scope
from scraper.version import __version__


runner = CliRunner()


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_init_config_command(tmp_path) -> None:
    target = tmp_path / "scraper.yml"
    result = runner.invoke(app, ["init-config", str(target)])
    assert result.exit_code == 0
    assert target.exists()
    contents = target.read_text(encoding="utf-8")
    assert "user_agent:" in contents
    assert "profile: minimal" in contents


def test_build_config_defaults_to_minimal_output_profile() -> None:
    config, overrides = _build_config(
        config_path=None,
        output_dir=None,
        browser_mode="auto",
        auto_interact_mode="auto",
        output_profile_mode="auto",
        verbose_mode=False,
        timeout_seconds=None,
        rate_limit=None,
        max_pages=None,
    )
    assert not overrides
    assert config.output.profile == OutputProfile.MINIMAL


def test_build_config_verbose_flag_overrides_output_profile() -> None:
    config, overrides = _build_config(
        config_path=None,
        output_dir=None,
        browser_mode="auto",
        auto_interact_mode="auto",
        output_profile_mode="minimal",
        verbose_mode=True,
        timeout_seconds=None,
        rate_limit=None,
        max_pages=None,
    )
    assert overrides["output"]["profile"] == "verbose"
    assert config.output.profile == OutputProfile.VERBOSE


class _StubArtifacts:
    def __init__(self, summary_path=None) -> None:
        self.summary_path = summary_path

    def save_json_document(self, *_args, **_kwargs):
        return self.summary_path


class _StubOrchestrator:
    def __init__(self, result: DocumentResult) -> None:
        self._result = result

    def scrape(self, *_args, **_kwargs) -> DocumentResult:
        return self._result


class _StubCrawler:
    def __init__(self, manifest: CrawlManifest) -> None:
        self._manifest = manifest

    def crawl(self, *_args, **_kwargs) -> CrawlManifest:
        return self._manifest


class _StubDiscovery:
    def __init__(self, bundle: DiscoveryBundle) -> None:
        self._bundle = bundle

    def discover(self, *_args, **_kwargs) -> DiscoveryBundle:
        return self._bundle


class _StubRuntime:
    def __init__(
        self,
        result: DocumentResult,
        summary_path=None,
        manifest: CrawlManifest | None = None,
        bundle: DiscoveryBundle | None = None,
    ) -> None:
        self.orchestrator = _StubOrchestrator(result)
        self.crawler = _StubCrawler(manifest or CrawlManifest(root_url="https://example.com", scope=Scope.SECTION))
        self.discovery = _StubDiscovery(
            bundle
            or DiscoveryBundle(
                requested_url="https://example.com",
                normalized_url="https://example.com",
                scope=Scope.PAGE,
            )
        )
        self.artifacts = _StubArtifacts(summary_path=summary_path)

    def close(self) -> None:
        return None


def test_scrape_default_output_is_markdown_path(monkeypatch, tmp_path) -> None:
    markdown_path = tmp_path / "output" / "run" / "markdown" / "example.md"
    result = DocumentResult(
        requested_url="https://example.com/docs",
        normalized_url="https://example.com/docs",
        success=True,
        markdown_path=markdown_path,
    )
    runtime = _StubRuntime(result, summary_path=None)
    monkeypatch.setattr("scraper.cli.RuntimeFactory.build", lambda _cfg: runtime)

    invoked = runner.invoke(app, ["scrape", "https://example.com/docs"])

    assert invoked.exit_code == 0
    collapsed_output = invoked.output.replace("\n", "")
    expected_path = str(markdown_path).replace("\n", "")
    assert expected_path in collapsed_output
    assert "Result summary" not in invoked.output
    assert "Extraction attempts" not in invoked.output


def test_scrape_verbose_output_shows_summary_tables(monkeypatch, tmp_path) -> None:
    markdown_path = tmp_path / "output" / "run" / "markdown" / "example.md"
    result = DocumentResult(
        requested_url="https://example.com/docs",
        normalized_url="https://example.com/docs",
        success=True,
        markdown_path=markdown_path,
        attempts=[
            ExtractionAttempt(
                mode=ExtractionMode.STATIC_HTML,
                success=True,
                url="https://example.com/docs",
                outcome="ok",
            ),
        ],
    )
    runtime = _StubRuntime(result, summary_path=tmp_path / "output" / "run" / "result.json")
    monkeypatch.setattr("scraper.cli.RuntimeFactory.build", lambda _cfg: runtime)

    invoked = runner.invoke(app, ["scrape", "https://example.com/docs", "--verbose"])

    assert invoked.exit_code == 0
    assert "Result summary" in invoked.output
    assert "Extraction attempts" in invoked.output


def test_crawl_default_output_is_markdown_paths(monkeypatch, tmp_path) -> None:
    markdown_path = tmp_path / "output" / "run" / "markdown" / "a.md"
    manifest = CrawlManifest(
        root_url="https://example.com/docs",
        scope=Scope.SECTION,
        entries=[
            CrawlManifestEntry(
                url="https://example.com/docs/a",
                success=True,
                extraction_mode=ExtractionMode.STATIC_HTML,
                markdown_path=str(markdown_path),
            ),
        ],
    )
    runtime = _StubRuntime(
        DocumentResult(requested_url="https://example.com/docs", normalized_url="https://example.com/docs", success=True),
        summary_path=None,
        manifest=manifest,
    )
    monkeypatch.setattr("scraper.cli.RuntimeFactory.build", lambda _cfg: runtime)

    invoked = runner.invoke(app, ["crawl", "https://example.com/docs"])

    assert invoked.exit_code == 0
    collapsed_output = invoked.output.replace("\n", "")
    expected_path = str(markdown_path).replace("\n", "")
    assert expected_path in collapsed_output
    assert "Crawl summary" not in invoked.output
    assert "Manifest:" not in invoked.output


def test_crawl_verbose_output_shows_summary_table(monkeypatch, tmp_path) -> None:
    manifest = CrawlManifest(
        root_url="https://example.com/docs",
        scope=Scope.SECTION,
        entries=[
            CrawlManifestEntry(
                url="https://example.com/docs/a",
                success=True,
                extraction_mode=ExtractionMode.STATIC_HTML,
                markdown_path=str(tmp_path / "output" / "run" / "markdown" / "a.md"),
            ),
        ],
    )
    runtime = _StubRuntime(
        DocumentResult(requested_url="https://example.com/docs", normalized_url="https://example.com/docs", success=True),
        summary_path=tmp_path / "output" / "run" / "crawl_manifest.json",
        manifest=manifest,
    )
    monkeypatch.setattr("scraper.cli.RuntimeFactory.build", lambda _cfg: runtime)

    invoked = runner.invoke(app, ["crawl", "https://example.com/docs", "--verbose"])

    assert invoked.exit_code == 0
    assert "Crawl summary" in invoked.output
    assert "Manifest:" in invoked.output


def test_inspect_default_output_shows_only_number_and_url_columns(monkeypatch, tmp_path) -> None:
    bundle = DiscoveryBundle(
        requested_url="https://example.com/docs",
        normalized_url="https://example.com/docs",
        scope=Scope.PAGE,
        candidates=[
            CandidateSource(
                kind=CandidateKind.API_ENDPOINT,
                url="https://example.com/api/page.json",
                confidence=0.81,
                cost=2,
                evidence=["json_url_in_script"],
            ),
        ],
    )
    runtime = _StubRuntime(
        DocumentResult(requested_url="https://example.com/docs", normalized_url="https://example.com/docs", success=True),
        summary_path=None,
        bundle=bundle,
    )
    monkeypatch.setattr("scraper.cli.RuntimeFactory.build", lambda _cfg: runtime)

    invoked = runner.invoke(app, ["inspect", "https://example.com/docs"])

    assert invoked.exit_code == 0
    assert "Ranked candidate sources" in invoked.output
    assert "URL" in invoked.output
    assert "Kind" not in invoked.output
    assert "Confidence" not in invoked.output
    assert "Cost" not in invoked.output
    assert "Evidence" not in invoked.output
    assert "https://example.com/api/page.json" in invoked.output


def test_inspect_verbose_output_shows_all_candidate_columns(monkeypatch, tmp_path) -> None:
    bundle = DiscoveryBundle(
        requested_url="https://example.com/docs",
        normalized_url="https://example.com/docs",
        scope=Scope.PAGE,
        candidates=[
            CandidateSource(
                kind=CandidateKind.API_ENDPOINT,
                url="https://example.com/api/page.json",
                confidence=0.81,
                cost=2,
                evidence=["json_url_in_script"],
            ),
        ],
    )
    runtime = _StubRuntime(
        DocumentResult(requested_url="https://example.com/docs", normalized_url="https://example.com/docs", success=True),
        summary_path=tmp_path / "output" / "run" / "discovery_bundle.json",
        bundle=bundle,
    )
    monkeypatch.setattr("scraper.cli.RuntimeFactory.build", lambda _cfg: runtime)

    invoked = runner.invoke(app, ["inspect", "https://example.com/docs", "--verbose"])

    assert invoked.exit_code == 0
    assert "Ranked candidate sources" in invoked.output
    assert "Kind" in invoked.output
    assert "Confidence" in invoked.output
    assert "Cost" in invoked.output
    assert "Evidence" in invoked.output
    assert "api_endpoint" in invoked.output
