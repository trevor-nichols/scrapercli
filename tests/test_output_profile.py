from scraper.observability.store import ArtifactPersistencePolicy, ArtifactStore


def test_minimal_profile_persists_markdown_only(tmp_path) -> None:
    store = ArtifactStore(tmp_path / "out", policy=ArtifactPersistencePolicy.minimal())

    markdown_path = store.save_markdown("https://example.com/docs", "# Hello")
    raw_path, body_hash = store.save_response(
        "https://example.com/docs",
        "GET",
        b"<html><body>Hello</body></html>",
        {"content-type": "text/html"},
        200,
    )
    metadata_path = store.save_metadata("https://example.com/docs", {"title": "Hello"})
    result_path = store.save_json_document("result.json", {"success": True})

    assert markdown_path.exists()
    assert body_hash
    assert raw_path is None
    assert metadata_path is None
    assert result_path is None
    assert store.decisions_path is None
    assert store.conditional_cache_path is None
    assert store.repetition_store_path is None
    assert not (store.root_dir / "raw").exists()
    assert not (store.root_dir / "metadata").exists()
    assert not (store.root_dir / "state").exists()
    assert not (store.root_dir / "logs").exists()


def test_verbose_profile_persists_full_artifacts(tmp_path) -> None:
    store = ArtifactStore(tmp_path / "out", policy=ArtifactPersistencePolicy.verbose())

    markdown_path = store.save_markdown("https://example.com/docs", "# Hello")
    raw_path, body_hash = store.save_response(
        "https://example.com/docs",
        "GET",
        b"<html><body>Hello</body></html>",
        {"content-type": "text/html"},
        200,
    )
    metadata_path = store.save_metadata("https://example.com/docs", {"title": "Hello"})
    result_path = store.save_json_document("result.json", {"success": True})

    assert markdown_path.exists()
    assert body_hash
    assert raw_path is not None and raw_path.exists()
    assert metadata_path is not None and metadata_path.exists()
    assert result_path is not None and result_path.exists()
    assert store.decisions_path is not None
    assert store.conditional_cache_path is not None
    assert store.repetition_store_path is not None
