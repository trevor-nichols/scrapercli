import json

from staged_scraper.extractors.http_replay import HTTPReplayExtractor
from staged_scraper.models import CandidateKind, CandidateSource, DiscoveryBundle, FetchSnapshot, Scope, ScraperConfig
from staged_scraper.observability.recorder import DecisionRecorder
from staged_scraper.observability.store import ArtifactStore


class StubHttpClient:
    def __init__(self, snapshot: FetchSnapshot) -> None:
        self.snapshot = snapshot

    def fetch(self, *args, **kwargs) -> FetchSnapshot:
        return self.snapshot


JSON_PAYLOAD = {
    "title": "API Document",
    "author": {"name": "API Author"},
    "content": "This content came from a replayed API response. " * 8,
}


def test_http_replay_extractor_converts_json_payload(tmp_path) -> None:
    snapshot = FetchSnapshot(
        url="https://example.com/api/page.json",
        final_url="https://example.com/api/page.json",
        method="GET",
        status_code=200,
        headers={"content-type": "application/json"},
        content_type="application/json",
        text=json.dumps(JSON_PAYLOAD),
    )
    extractor = HTTPReplayExtractor(StubHttpClient(snapshot), DecisionRecorder(tmp_path / "decisions.jsonl"))
    bundle = DiscoveryBundle(
        requested_url="https://example.com/docs/page",
        normalized_url="https://example.com/docs/page",
        scope=Scope.PAGE,
        candidates=[CandidateSource(kind=CandidateKind.API_ENDPOINT, url=snapshot.url, confidence=0.8)],
    )

    attempt = extractor.run(bundle)

    assert attempt.success
    assert attempt.document is not None
    assert "# API Document" in attempt.document.markdown
    assert "API Author" in attempt.document.markdown
