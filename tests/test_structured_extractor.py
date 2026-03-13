from staged_scraper.extractors.structured import StructuredDataExtractor
from staged_scraper.models import CandidateKind, CandidateSource, DiscoveryBundle, FetchSnapshot, Scope
from staged_scraper.observability.recorder import DecisionRecorder


PAYLOAD = {
    "pageProps": {
        "title": "Hydrated Page",
        "author": {"name": "Casey Example"},
        "contentMarkdown": "## Section\n\nThis body came from structured data and should be preferred before HTML DOM scraping.",
    }
}


def test_structured_extractor_prefers_markdown_payload(tmp_path) -> None:
    recorder = DecisionRecorder(tmp_path / "decisions.jsonl")
    extractor = StructuredDataExtractor(recorder)
    page = FetchSnapshot(
        url="https://example.com/docs/page",
        final_url="https://example.com/docs/page",
        method="GET",
        status_code=200,
        headers={"content-type": "text/html"},
        content_type="text/html",
        text="<html><body><div id='__next'></div></body></html>",
    )
    bundle = DiscoveryBundle(
        requested_url=page.url,
        normalized_url=page.url,
        scope=Scope.PAGE,
        page=page,
        candidates=[CandidateSource(kind=CandidateKind.HYDRATION, payload=PAYLOAD, confidence=0.9)],
    )

    attempt = extractor.run(bundle)

    assert attempt.success
    assert attempt.document is not None
    assert "# Hydrated Page" in attempt.document.markdown
    assert "## Section" in attempt.document.markdown
    assert attempt.document.metadata.author == "Casey Example"
