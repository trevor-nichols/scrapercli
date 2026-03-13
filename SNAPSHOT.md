<project_structure>
├── src
│   └── staged_scraper
│       ├── adapters
│       │   ├── __init__.py
│       │   ├── base.py
│       │   └── registry.py
│       ├── discovery
│       │   ├── __init__.py
│       │   ├── framework.py
│       │   ├── llms.py
│       │   ├── probes.py
│       │   └── sitemap.py
│       ├── extractors
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── browser.py
│       │   ├── html_static.py
│       │   ├── http_replay.py
│       │   ├── publisher_markdown.py
│       │   └── structured.py
│       ├── html
│       │   ├── __init__.py
│       │   ├── markdown.py
│       │   ├── metadata.py
│       │   ├── repetition.py
│       │   └── scoring.py
│       ├── http
│       │   ├── __init__.py
│       │   ├── cache.py
│       │   ├── client.py
│       │   └── robots.py
│       ├── observability
│       │   ├── __init__.py
│       │   ├── recorder.py
│       │   └── store.py
│       ├── pipeline
│       │   ├── __init__.py
│       │   ├── crawler.py
│       │   ├── orchestrator.py
│       │   └── quality.py
│       ├── utils
│       │   ├── __init__.py
│       │   ├── dom.py
│       │   ├── hashing.py
│       │   ├── text.py
│       │   └── url.py
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── config.py
│       ├── models.py
│       ├── runtime.py
│       └── version.py
├── tests
│   ├── fixtures
│   │   ├── article_page.html
│   │   └── nextjs_page.html
│   ├── test_cli.py
│   ├── test_framework.py
│   ├── test_http_replay.py
│   ├── test_llms.py
│   ├── test_markdown_renderer.py
│   ├── test_orchestrator.py
│   ├── test_sitemap.py
│   ├── test_static_html_extractor.py
│   └── test_structured_extractor.py
├── pyproject.toml
├── scraper.example.yml
└── uv.lock
</project_structure>
