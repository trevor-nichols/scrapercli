from staged_scraper.discovery.sitemap import SitemapDiscovery
from staged_scraper.models import FetchSnapshot
from staged_scraper.observability.recorder import DecisionRecorder


class StubHttpClient:
    def __init__(self, responses: dict[str, str]) -> None:
        self._responses = responses

    def fetch(self, url: str, allow_status: set[int] | None = None) -> FetchSnapshot:
        text = self._responses.get(url)
        status_code = 200 if text is not None else 404
        return FetchSnapshot(
            url=url,
            final_url=url,
            method="GET",
            status_code=status_code,
            headers={"content-type": "application/xml"},
            content_type="application/xml",
            text=text,
        )


def test_gather_urls_accepts_max_pages_keyword(tmp_path) -> None:
    sitemap_url = "https://docs.example.com/sitemap.xml"
    root_url = "https://docs.example.com/guides/overview/quick-start"
    sitemap_xml = """
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://docs.example.com/guides/overview/quick-start</loc></url>
      <url><loc>https://docs.example.com/guides/overview/quick-start/install</loc></url>
      <url><loc>https://docs.example.com/guides/overview/quick-start/auth</loc></url>
      <url><loc>https://docs.example.com/blog/release-notes</loc></url>
    </urlset>
    """
    client = StubHttpClient({sitemap_url: sitemap_xml})
    recorder = DecisionRecorder(tmp_path / "decisions.jsonl")
    discovery = SitemapDiscovery(client, recorder)

    urls = discovery.gather_urls([sitemap_url], root_url, max_pages=2)

    assert len(urls) == 2
    assert all(url.startswith("https://docs.example.com/guides/overview/quick-start") for url in urls)
