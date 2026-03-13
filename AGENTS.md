You are working a the scraper cli, a web scraper cli tool that scrapes urls to a markdown file.

## Development Notes
- Hold the implementation to production-grade standards: clean architecture, DRY, minimal coupling, clear module boundaries, predictable conventions and maintainable patterns.
- Throughout the codebase you will see SNAPSHOT.md files. These files contain architectural documentation using directory trees with inline comments to help you understand and navigate the project efficiently. You can update these by running `just update-snapshots` (preserves comments, but does not add comments). You can identify all SNAPSHOT.md files in repo by running `just locate-snapshots`.
- Keep this AGENTS.md file up-to-date and update/edit for any significant changes.

<project_structure>
├── src/  # Source code root
│   └── scraper/  # Main package directory
│       ├── adapters/  # Framework-specific HTML parsing logic
│       │   ├── __init__.py  # Adapter registry exports
│       │   ├── base.py  # Base class for framework adapters
│       │   └── registry.py  # Registry mapping frameworks (Next.js, Docusaurus) to adapters
│       ├── discovery/  # Mechanisms to discover content sources and APIs
│       │   ├── __init__.py  # Discovery module exports
│       │   ├── framework.py  # Detects frontend frameworks (e.g., Next.js, Astro) from HTML
│       │   ├── llms.py  # Parses llms.txt and llms-full.txt to find raw markdown
│       │   ├── probes.py  # Main discovery engine for APIs, inline state, and linked files
│       │   └── sitemap.py  # XML sitemap parser and URL gatherer
│       ├── extractors/  # Implementations of different content extraction strategies
│       │   ├── __init__.py  # Extractor module exports
│       │   ├── base.py  # Protocol defining the extractor interface
│       │   ├── browser.py  # Browser-based extraction (DOM reading, network capture) via Playwright
│       │   ├── html_static.py  # Content extraction from static HTML via structural scoring
│       │   ├── http_replay.py  # Content extraction by replaying discovered API/GraphQL endpoints
│       │   ├── publisher_markdown.py  # Direct extraction from publisher-provided raw markdown files
│       │   └── structured.py  # Content extraction from inline structured data (JSON-LD, hydration)
│       ├── html/  # HTML processing, scoring, and transformation tools
│       │   ├── __init__.py  # HTML module exports
│       │   ├── markdown.py  # Converts DOM nodes and HTML into formatted Markdown
│       │   ├── metadata.py  # Extracts page metadata (title, author, dates) from HTML tags and JSON-LD
│       │   ├── repetition.py  # Tracks boilerplate/repeated HTML fragments across a domain
│       │   └── scoring.py  # Evaluates DOM nodes to differentiate main body content from chrome/nav
│       ├── http/  # HTTP client operations and policies
│       │   ├── __init__.py  # HTTP module exports
│       │   ├── cache.py  # Local cache for conditional requests (ETag, Last-Modified)
│       │   ├── client.py  # Wrapped HTTPX client handling retries and rate limiting
│       │   └── robots.py  # Parses and enforces robots.txt directives
│       ├── observability/  # Logging, telemetry, and artifact storage
│       │   ├── __init__.py  # Observability module exports
│       │   ├── recorder.py  # Records extraction decisions and pipeline escalations
│       │   └── store.py  # Saves raw responses, markdown, and metadata to disk
│       ├── pipeline/  # High-level scraping orchestration
│       │   ├── __init__.py  # Pipeline module exports
│       │   ├── crawler.py  # Coordinates crawling multiple pages from a root URL
│       │   ├── orchestrator.py  # Stages extractors and escalates if quality thresholds fail
│       │   └── quality.py  # Assesses the quality of extracted markdown (length, structure, chrome)
│       ├── utils/  # General helper functions
│       │   ├── __init__.py  # Utils module exports
│       │   ├── dom.py  # BeautifulSoup instantiation helper
│       │   ├── hashing.py  # SHA256 hashing utilities for strings and bytes
│       │   ├── text.py  # Text normalization, heuristics, and feature extraction
│       │   └── url.py  # URL parsing, normalization, and manipulation utilities
│       ├── __init__.py  # Package exports
│       ├── __main__.py  # Entry point for module execution
│       ├── cli.py  # Command-line interface definitions (scrape, crawl, inspect)
│       ├── config.py  # Configuration loading and merging logic
│       ├── models.py  # Pydantic data models for configuration, state, and outputs
│       ├── runtime.py  # Dependency injection factory initializing the scraping runtime
│       └── version.py  # Package version definition
├── tests/  # Automated test suite
│   ├── fixtures/  # Static test files
│   │   ├── article_page.html  # Example blog article HTML for extraction tests
│   │   └── nextjs_page.html  # Example Next.js HTML with hydration payload
│   ├── test_cli.py  # Tests for CLI commands and arguments
│   ├── test_framework.py  # Tests for framework detection logic
│   ├── test_http_replay.py  # Tests for API endpoint replay extraction
│   ├── test_llms.py  # Tests for parsing llms.txt discovery
│   ├── test_markdown_renderer.py  # Tests for HTML-to-Markdown conversion
│   ├── test_orchestrator.py  # Tests for extraction escalation and pipeline logic
│   ├── test_sitemap.py  # Tests for sitemap fetching and parsing
│   ├── test_static_html_extractor.py  # Tests for static HTML structural scoring and extraction
│   └── test_structured_extractor.py  # Tests for extracting inline JSON and state payloads
├── pyproject.toml  # Project metadata and dependencies
├── scraper.example.yml  # Example YAML configuration for the scraper
└── uv.lock  # UV package manager dependency lockfile
</project_structure>
