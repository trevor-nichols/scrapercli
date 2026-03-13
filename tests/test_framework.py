from pathlib import Path

from staged_scraper.discovery.framework import FrameworkDetectorRegistry
from staged_scraper.models import FrameworkFamily


def test_framework_detector_identifies_nextjs() -> None:
    html = Path("tests/fixtures/nextjs_page.html").read_text(encoding="utf-8")
    hint = FrameworkDetectorRegistry().detect(html, "https://example.com/docs/page")

    assert hint.framework_family == FrameworkFamily.NEXTJS
    assert hint.confidence_score >= 0.8
    assert any("__NEXT_DATA__" in evidence for evidence in hint.evidence)
