from staged_scraper.discovery.llms import LLMSDiscovery, score_markdown_candidate
from staged_scraper.models import CandidateKind, FetchSnapshot, Scope


def test_llms_snapshot_parses_markdown_and_llms_full_candidates() -> None:
    snapshot = FetchSnapshot(
        url="https://example.com/docs/llms.txt",
        final_url="https://example.com/docs/llms.txt",
        method="GET",
        status_code=200,
        headers={"content-type": "text/plain"},
        content_type="text/plain",
        text="""
        # Docs
        - [Getting started](./guide/getting-started.md)
        - https://example.com/docs/llms-full.txt
        """,
    )
    discovery = LLMSDiscovery()

    candidates = discovery.parse_snapshot(snapshot, "https://example.com/docs/guide/getting-started", Scope.PAGE)

    assert candidates
    assert candidates[0].kind == CandidateKind.LINKED_MARKDOWN
    assert candidates[0].url == "https://example.com/docs/guide/getting-started.md"
    assert any(candidate.kind == CandidateKind.LLMS_FULL for candidate in candidates)


def test_markdown_candidate_scoring_matches_page_markdown_exactly() -> None:
    exact = score_markdown_candidate(
        "https://example.com/docs/guide/getting-started.md",
        "https://example.com/docs/guide/getting-started",
        Scope.PAGE,
        from_llms=True,
    )
    sibling = score_markdown_candidate(
        "https://example.com/docs/guide/index.md",
        "https://example.com/docs/guide/getting-started",
        Scope.PAGE,
        from_llms=True,
    )

    assert exact > sibling


def test_llms_snapshot_ignores_malformed_bare_url_tokens() -> None:
    snapshot = FetchSnapshot(
        url="https://example.com/docs/llms-full.txt",
        final_url="https://example.com/docs/llms-full.txt",
        method="GET",
        status_code=200,
        headers={"content-type": "text/plain"},
        content_type="text/plain",
        text="""
        "authorization_servers": ["https://auth.yourcompany.com"],
        - https://example.com/docs/llms-full.txt
        """,
    )
    discovery = LLMSDiscovery()

    candidates = discovery.parse_snapshot(snapshot, "https://example.com/docs/getting-started", Scope.PAGE)

    assert candidates
    assert any(candidate.kind == CandidateKind.LLMS_FULL for candidate in candidates)
    assert all(candidate.url != 'https://auth.yourcompany.com"],' for candidate in candidates if candidate.url)


def test_llms_snapshot_skips_urls_inside_fenced_code_blocks() -> None:
    snapshot = FetchSnapshot(
        url="https://example.com/docs/llms-full.txt",
        final_url="https://example.com/docs/llms-full.txt",
        method="GET",
        status_code=200,
        headers={"content-type": "text/plain"},
        content_type="text/plain",
        text="""
        ```json
        "authorization_servers": ["https://auth.yourcompany.com"],
        ```
        - [Guide](./guide.md)
        """,
    )
    discovery = LLMSDiscovery()

    candidates = discovery.parse_snapshot(snapshot, "https://example.com/docs/getting-started", Scope.PAGE)

    assert any(candidate.url == "https://example.com/docs/guide.md" for candidate in candidates)
    assert all(candidate.url != "https://auth.yourcompany.com" for candidate in candidates if candidate.url)
