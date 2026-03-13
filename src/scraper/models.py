from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class Scope(str, Enum):
    PAGE = "page"
    SECTION = "section"
    SITE = "site"


class ExtractionMode(str, Enum):
    PUBLISHER_MARKDOWN = "publisher_markdown"
    STRUCTURED_HTTP = "structured_http"
    STATIC_HTML = "static_html"
    HTTP_REPLAY = "http_replay"
    BROWSER_DISCOVERY = "browser_discovery"
    BROWSER_DOM = "browser_dom"


class CandidateKind(str, Enum):
    LLMS_TXT = "llms_txt"
    LLMS_FULL = "llms_full"
    LINKED_MARKDOWN = "linked_markdown"
    MARKDOWN_TWIN = "markdown_twin"
    JSON_LD = "json_ld"
    HYDRATION = "hydration"
    INLINE_STATE = "inline_state"
    API_ENDPOINT = "api_endpoint"
    GRAPHQL_ENDPOINT = "graphql_endpoint"
    HTML_PAGE = "html_page"
    BROWSER_CAPTURED_ENDPOINT = "browser_captured_endpoint"
    BROWSER_DOM = "browser_dom"
    ROBOTS = "robots"
    SITEMAP = "sitemap"


class FrameworkFamily(str, Enum):
    NEXTJS = "nextjs"
    ASTRO = "astro"
    DOCUSAURUS = "docusaurus"
    VITEPRESS = "vitepress"
    MINTLIFY = "mintlify"
    GENERIC_STATIC = "generic_static"
    GENERIC_APP_SHELL = "generic_app_shell"
    UNKNOWN = "unknown"


class ContentKind(str, Enum):
    MARKDOWN = "markdown"
    HTML = "html"
    JSON = "json"
    TEXT = "text"
    BLOCKS = "blocks"


class DecisionEvent(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    level: str = "info"
    stage: str
    url: str
    event: str
    details: dict[str, Any] = Field(default_factory=dict)


class RateLimitConfig(BaseModel):
    requests_per_second: float = 1.0
    burst: int = 1


class RetryConfig(BaseModel):
    attempts: int = 3
    backoff_seconds: float = 0.75
    backoff_multiplier: float = 2.0
    retryable_status_codes: list[int] = Field(default_factory=lambda: [429, 500, 502, 503, 504])


class BrowserConfig(BaseModel):
    enabled: bool = False
    timeout_ms: int = 30000
    wait_until: str = "networkidle"
    auto_interact: bool = False
    max_auto_clicks: int = 8
    headless: bool = True


class OutputConfig(BaseModel):
    root_dir: Path = Path("./output")
    frontmatter: bool = True
    metadata_sidecar: bool = True
    raw_sources: bool = True
    deterministic_filenames: bool = True


class CrawlConfig(BaseModel):
    scope: Scope = Scope.PAGE
    max_pages: int = 50
    concurrency: int = 1
    same_host_only: bool = True
    respect_robots: bool = True
    follow_sitemaps: bool = True
    max_depth: int = 4


class QualityThresholds(BaseModel):
    min_chars_normal_page: int = 600
    thin_page_chars: int = 300
    min_body_score: float = 25.0
    min_body_minus_chrome: float = 10.0
    min_paragraphs: int = 3


class ScraperConfig(BaseModel):
    user_agent: str = "/0.1.0 (+https://example.invalid/)"
    timeout_seconds: float = 25.0
    default_headers: dict[str, str] = Field(default_factory=dict)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    crawl: CrawlConfig = Field(default_factory=CrawlConfig)
    quality: QualityThresholds = Field(default_factory=QualityThresholds)
    cookies: dict[str, str] = Field(default_factory=dict)
    proxies: dict[str, str] = Field(default_factory=dict)


class FetchSnapshot(BaseModel):
    url: str
    final_url: str
    method: str
    status_code: int
    headers: dict[str, str]
    content_type: str | None = None
    text: str | None = None
    body_sha256: str | None = None
    artifact_path: Path | None = None
    is_not_modified: bool = False
    etag: str | None = None
    last_modified: str | None = None
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300 or self.status_code == 304

    @property
    def is_html(self) -> bool:
        return bool(self.content_type and "html" in self.content_type.lower())

    @property
    def is_json(self) -> bool:
        return bool(self.content_type and "json" in self.content_type.lower())

    @property
    def is_markdown(self) -> bool:
        if not self.content_type:
            return False
        lowered = self.content_type.lower()
        return any(token in lowered for token in ["markdown", "text/plain", "text/x-markdown"])


class CandidateSource(BaseModel):
    kind: CandidateKind
    url: str | None = None
    method: str = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    body: str | None = None
    payload: dict[str, Any] | list[Any] | None = None
    confidence: float = 0.0
    cost: int = 0
    evidence: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FrameworkHint(BaseModel):
    framework_family: FrameworkFamily = FrameworkFamily.UNKNOWN
    confidence_score: float = 0.0
    evidence: list[str] = Field(default_factory=list)
    suggested_extraction_strategy: str = "html"
    suggested_content_sources: list[str] = Field(default_factory=list)


class RobotsInfo(BaseModel):
    url: str
    text: str = ""
    allowed: bool = True
    sitemaps: list[str] = Field(default_factory=list)


class StructuredContentCandidate(BaseModel):
    path: str
    kind: ContentKind
    value: str | dict[str, Any] | list[Any]
    score: float
    evidence: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PageMetadata(BaseModel):
    source_url: str
    canonical_url: str | None = None
    title: str | None = None
    description: str | None = None
    author: str | None = None
    published_at: str | None = None
    modified_at: str | None = None
    language: str | None = None
    content_type: str | None = None
    open_graph: dict[str, str] = Field(default_factory=dict)
    twitter: dict[str, str] = Field(default_factory=dict)
    structured_metadata: dict[str, Any] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)


class NodeFeatureSet(BaseModel):
    xpath_like: str
    tag: str
    text_chars: int = 0
    linked_text_chars: int = 0
    link_density: float = 0.0
    paragraph_count: int = 0
    avg_paragraph_length: float = 0.0
    heading_count: int = 0
    has_h1_or_h2: bool = False
    has_time_or_byline: bool = False
    code_blocks: int = 0
    tables: int = 0
    lists: int = 0
    blockquotes: int = 0
    form_controls: int = 0
    buttons: int = 0
    dom_depth: int = 0
    relative_position: float = 0.0
    landmark: str | None = None
    repetition_score: float = 0.0
    keyword_hits: list[str] = Field(default_factory=list)
    near_title: bool = False
    nested_inside_article_or_main: bool = False


class NodeScore(BaseModel):
    xpath_like: str
    tag: str
    body_score: float
    chrome_score: float
    metadata_preserve_score: float
    keep_in_body: bool
    drop_as_chrome: bool
    preserve_as_metadata: bool
    features: NodeFeatureSet
    reasons: list[str] = Field(default_factory=list)


class HTMLExtractionDiagnostics(BaseModel):
    winner_xpath: str | None = None
    body_score: float = 0.0
    chrome_score: float = 0.0
    metadata_preserve_score: float = 0.0
    paragraph_count: int = 0
    node_scores: list[NodeScore] = Field(default_factory=list)
    body_chars: int = 0
    signals: list[str] = Field(default_factory=list)


class MarkdownDocument(BaseModel):
    markdown: str
    metadata: PageMetadata
    content_kind: ContentKind = ContentKind.MARKDOWN
    source_kind: CandidateKind | None = None
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class QualityReport(BaseModel):
    passed: bool
    body_chars: int
    heading_count: int
    paragraph_count: int
    title_present: bool
    code_fence_count: int = 0
    table_count: int = 0
    reasons: list[str] = Field(default_factory=list)
    comparison: dict[str, Any] = Field(default_factory=dict)


class ExtractionAttempt(BaseModel):
    mode: ExtractionMode
    success: bool = False
    url: str
    trigger_condition: str | None = None
    observed_signals: list[str] = Field(default_factory=list)
    outcome: str = ""
    candidate_urls: list[str] = Field(default_factory=list)
    document: MarkdownDocument | None = None
    quality: QualityReport | None = None
    elapsed_ms: int = 0
    extra: dict[str, Any] = Field(default_factory=dict)


class DiscoveryBundle(BaseModel):
    requested_url: str
    normalized_url: str
    scope: Scope = Scope.PAGE
    page: FetchSnapshot | None = None
    llms_snapshots: list[FetchSnapshot] = Field(default_factory=list)
    robots: RobotsInfo | None = None
    sitemap_urls: list[str] = Field(default_factory=list)
    candidates: list[CandidateSource] = Field(default_factory=list)
    framework_hint: FrameworkHint = Field(default_factory=FrameworkHint)
    metadata: PageMetadata | None = None
    signals: list[str] = Field(default_factory=list)


class DocumentResult(BaseModel):
    requested_url: str
    normalized_url: str
    final_url: str | None = None
    scope: Scope = Scope.PAGE
    success: bool = False
    attempts: list[ExtractionAttempt] = Field(default_factory=list)
    document: MarkdownDocument | None = None
    decisions_path: Path | None = None
    markdown_path: Path | None = None
    metadata_path: Path | None = None
    raw_bundle_dir: Path | None = None
    manifest_path: Path | None = None
    errors: list[str] = Field(default_factory=list)


class CrawlManifestEntry(BaseModel):
    url: str
    success: bool
    extraction_mode: ExtractionMode | None = None
    markdown_path: str | None = None
    metadata_path: str | None = None
    reasons: list[str] = Field(default_factory=list)


class CrawlManifest(BaseModel):
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    root_url: str
    scope: Scope
    entries: list[CrawlManifestEntry] = Field(default_factory=list)


class RepetitionStore(BaseModel):
    host: str
    pages_seen: int = 0
    signatures: dict[str, int] = Field(default_factory=dict)


class BrowserCapturedRequest(BaseModel):
    url: str
    method: str
    headers: dict[str, str] = Field(default_factory=dict)
    post_data: str | None = None
    resource_type: str | None = None
    response_status: int | None = None
    response_headers: dict[str, str] = Field(default_factory=dict)
    response_body: str | None = None


class BrowserDiscoveryResult(BaseModel):
    dom_html: str | None = None
    requests: list[BrowserCapturedRequest] = Field(default_factory=list)
    candidate_sources: list[CandidateSource] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)
