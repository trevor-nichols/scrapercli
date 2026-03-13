from pathlib import Path

from staged_scraper.html.metadata import MetadataExtractor
from staged_scraper.html.repetition import RepetitionIndex
from staged_scraper.extractors.html_static import StaticHTMLExtractor
from staged_scraper.models import DiscoveryBundle, FetchSnapshot, Scope
from staged_scraper.observability.recorder import DecisionRecorder


def test_static_html_extractor_prefers_article_and_prunes_chrome(tmp_path) -> None:
    html = Path("tests/fixtures/article_page.html").read_text(encoding="utf-8")
    recorder = DecisionRecorder(tmp_path / "decisions.jsonl")
    repetition = RepetitionIndex(tmp_path / "repetition.json")
    extractor = StaticHTMLExtractor(recorder, repetition)
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
        metadata=MetadataExtractor().extract(html, page.url),
    )

    attempt = extractor.run(bundle)

    assert attempt.success
    assert attempt.document is not None
    markdown = attempt.document.markdown
    assert "# Example Article" in markdown
    assert "Top Nav" not in markdown
    assert "Privacy" not in markdown
    assert "```python" in markdown
    assert "| Mode | Cost |" in markdown
    assert "https://example.com/blog/follow-up" in markdown
