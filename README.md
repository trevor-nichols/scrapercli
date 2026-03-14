# scraper cli

`scraper` is an HTTP-first, staged extraction CLI that converts websites into deterministic, clean Markdown while preserving raw source artifacts and recording every extraction decision.

It follows a strict escalation model:

1. Publisher-provided LLM-friendly documents (`llms.txt`, `llms-full.txt`, linked Markdown, Markdown twins)
2. Structured data discovered in HTTP responses (JSON-LD, hydration payloads, inline state)
3. Static HTML extraction with landmark-aware scoring and boilerplate pruning
4. Direct HTTP replay of discovered API/GraphQL endpoints
5. Browser-assisted discovery only when required
6. Browser-resident DOM extraction as the final fallback

## Why this tool exists

Most scrapers start at the rendered DOM and stay there. This project does not.

It prefers the least lossy, lowest-cost source first, keeps browser usage explicit and measurable, and produces Markdown suitable for both human reading and downstream LLM pipelines.

## Key properties

- HTTP-first acquisition
- `llms.txt` and Markdown-first discovery
- Structured-content preference over DOM scraping
- Landmark-aware HTML pruning with body/chrome/metadata scoring
- Cross-page repetition detection for boilerplate down-weighting
- Conditional requests with `ETag` / `Last-Modified`
- Optional raw-source retention for replay and debugging (verbose profile)
- Minimal-by-default artifact persistence (Markdown only)
- Verbose profile for full audit artifacts (`raw`, `metadata`, `state`, `logs`, run JSON)
- Deterministic frontmatter and Markdown normalization
- Optional Playwright-based browser escalation
- Extensible detector, adapter, and extractor registries

## Installation

### Core

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Browser fallback support

```bash
pip install -e '.[browser]'
playwright install chromium
```

## CLI

### Scrape a single page

```bash
 scrape https://example.com/docs/getting-started --output-dir ./output
```

### Emit the Markdown to stdout as well

```bash
 scrape https://example.com/docs/getting-started --stdout
```

### Keep full debug/audit artifacts (legacy behavior)

```bash
 scrape https://example.com/docs/getting-started --verbose
```

### Inspect discovery without full extraction

```bash
 inspect https://example.com/docs/getting-started
```

### Crawl a section

```bash
 crawl https://example.com/docs --scope section --max-pages 50 --output-dir ./output
```

### Crawl with detailed table output

```bash
 crawl https://example.com/docs --scope section --max-pages 50 --verbose
```

### Generate a starter config

```bash
 init-config ./scraper.yml
```

## Config

The CLI accepts a YAML config file:

```bash
 scrape https://example.com --config ./scraper.yml
```

Starter file:

```yaml
user_agent: /0.1.0 (+https://example.invalid/)
timeout_seconds: 25.0
rate_limit:
  requests_per_second: 1.0
  burst: 1
retry:
  attempts: 3
  backoff_seconds: 0.75
  backoff_multiplier: 2.0
  retryable_status_codes: [429, 500, 502, 503, 504]
browser:
  enabled: false
  timeout_ms: 30000
  wait_until: networkidle
  auto_interact: false
  max_auto_clicks: 8
  headless: true
output:
  root_dir: ./output
  profile: minimal
  frontmatter: true
  metadata_sidecar: true
  raw_sources: true
  deterministic_filenames: true
crawl:
  scope: page
  max_pages: 50
  concurrency: 1
  same_host_only: true
  respect_robots: true
  follow_sitemaps: true
  max_depth: 4
quality:
  min_chars_normal_page: 600
  thin_page_chars: 300
  min_body_score: 25.0
  min_body_minus_chrome: 10.0
  min_paragraphs: 3
cookies: {}
proxies: {}
```

`output.profile` controls persistence level:

- `minimal` (default): writes only Markdown artifacts
- `verbose`: writes full artifacts (`raw`, `metadata`, `state`, `logs`, run summary JSON)

CLI override:

```bash
 scrape https://example.com --output-profile verbose
 # or shorthand
 scrape https://example.com --verbose
```

`--verbose` enables full artifact persistence and detailed console tables.  
Default console output is concise:

- `scrape`: prints the single Markdown path
- `crawl`: prints Markdown paths for crawled pages
- `inspect`: candidate table shows `#` and `URL` only

Verbose console output includes full details:

- `scrape`: result summary + extraction attempts
- `crawl`: crawl summary table + manifest path
- `inspect`: full candidate columns (`Kind`, `Confidence`, `Cost`, `Evidence`)

## Output layout

Each CLI run writes into a timestamped run directory under the configured output root.

Default (`output.profile: minimal`):

```text
output/
  20260311T000000Z/
    markdown/
```

Verbose (`output.profile: verbose`):

```text
output/
  20260311T000000Z/
    raw/
    markdown/
    metadata/
    state/
      validators.json
      repetition.json
    logs/
      decisions.jsonl
    result.json
    crawl_manifest.json
    discovery_bundle.json
```

## Decision logging

When `output.profile` is `verbose`, every decision is written to `logs/decisions.jsonl`, including:

- HTTP fetches and retry events
- `llms.txt` probe hits/misses
- escalation mode changes
- extraction attempt outcomes

This keeps browser usage and fallback behavior auditable.

## Architecture overview

### Discovery

- URL normalization
- `robots.txt` fetch and policy registration
- `llms.txt` / `llms-full.txt` probing at root and section paths
- target page fetch
- metadata extraction
- framework detection
- Markdown twin probing
- structured candidate discovery from scripts and page links

### Extraction

- `PublisherMarkdownExtractor`
- `StructuredDataExtractor`
- `StaticHTMLExtractor`
- `HTTPReplayExtractor`
- `BrowserDiscoveryExtractor`
- `BrowserDOMExtractor`

### HTML extraction model

HTML extraction does not drop nodes by tag name alone.

It computes three scores per candidate node:

- body score
- chrome score
- metadata-preserve score

The winning subtree is selected using semantic landmarks, text density, structure, link density, repeated-template detection, and metadata signals.

## Extensibility points

- `discovery/framework.py`: detector registry
- `adapters/registry.py`: framework-aware adapter registry
- `extractors/`: staged extraction implementations
- `pipeline/orchestrator.py`: escalation control plane
- `pipeline/quality.py`: quality gating and retry decisions

## Tests

```bash
pytest
```

## Notes

- Public-content retrieval only. Do not use this project for unsafe or unauthorized access.
- Browser mode is intentionally optional and should remain rare in steady-state usage.
