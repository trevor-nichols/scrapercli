from __future__ import annotations

from collections import deque
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..discovery.sitemap import SitemapDiscovery
from ..models import CrawlManifest, CrawlManifestEntry, Scope
from ..utils.url import normalize_url, same_host, same_section
from .orchestrator import ScrapeOrchestrator


class Crawler:
    def __init__(self, orchestrator: ScrapeOrchestrator, sitemap_discovery: SitemapDiscovery) -> None:
        self.orchestrator = orchestrator
        self.sitemap_discovery = sitemap_discovery

    def crawl(self, root_url: str, scope: Scope, max_pages: int) -> CrawlManifest:
        targets = self.discover_targets(root_url, scope, max_pages)
        manifest = CrawlManifest(root_url=root_url, scope=scope)
        for target in targets:
            result = self.orchestrator.scrape(target, Scope.PAGE)
            entry = CrawlManifestEntry(
                url=target,
                success=result.success,
                extraction_mode=result.attempts[-1].mode if result.attempts else None,
                markdown_path=str(result.markdown_path) if result.markdown_path else None,
                metadata_path=str(result.metadata_path) if result.metadata_path else None,
                reasons=result.errors or ([reason for attempt in result.attempts for reason in (attempt.quality.reasons if attempt.quality else [])] if result.attempts else []),
            )
            manifest.entries.append(entry)
        return manifest

    def discover_targets(self, root_url: str, scope: Scope, max_pages: int) -> list[str]:
        normalized = normalize_url(root_url)
        if scope == Scope.PAGE:
            return [normalized]
        discovery = self.orchestrator.discovery_engine.discover(normalized, scope)
        targets = [normalized]
        if discovery.sitemap_urls:
            targets.extend(self.sitemap_discovery.gather_urls(discovery.sitemap_urls, normalized, max_pages=max_pages))
        if len(targets) < max_pages and discovery.page and discovery.page.text and discovery.page.is_html:
            targets.extend(extract_links(discovery.page.text, normalized, limit=max_pages))
        deduped = []
        seen = set()
        for target in targets:
            if target not in seen:
                seen.add(target)
                deduped.append(target)
            if len(deduped) >= max_pages:
                break
        return deduped



def extract_links(html: str, root_url: str, limit: int) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    found: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href_raw = str(anchor["href"]).strip()
        if not href_raw or href_raw.startswith("#"):
            continue
        lowered = href_raw.lower()
        if lowered.startswith(("mailto:", "tel:", "javascript:")):
            continue
        href = normalize_url(urljoin(root_url, href_raw))
        if same_host(root_url, href) and same_section(root_url, href):
            found.append(href)
        if len(found) >= limit:
            break
    return found
