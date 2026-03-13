from __future__ import annotations

import re

from ..models import ExtractionMode, MarkdownDocument, QualityReport, QualityThresholds
from ..utils.text import code_fence_count, heading_count_from_markdown, paragraph_count_from_text, table_count_from_markdown


FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.S)
CHROME_PHRASES = ["privacy", "terms", "cookies", "subscribe", "related posts", "sign in"]


class QualityAssessor:
    def __init__(self, thresholds: QualityThresholds) -> None:
        self.thresholds = thresholds

    def assess(self, document: MarkdownDocument, mode: ExtractionMode) -> QualityReport:
        markdown = document.markdown.strip()
        body = FRONTMATTER_RE.sub("", markdown).strip()
        body_chars = len(body)
        heading_count = heading_count_from_markdown(body)
        paragraph_count = paragraph_count_from_text(body)
        code_count = code_fence_count(body)
        table_count = table_count_from_markdown(body)
        reasons: list[str] = []
        diagnostics = document.diagnostics
        title_present = bool(document.metadata.title)

        if body_chars < self.thresholds.thin_page_chars:
            reasons.append(f"body_too_short<{self.thresholds.thin_page_chars}")
        if heading_count == 0 and paragraph_count < 2 and code_count == 0 and table_count == 0:
            reasons.append("insufficient_structure")
        lowered = body.lower()
        chrome_hits = sum(1 for phrase in CHROME_PHRASES if phrase in lowered)
        if chrome_hits >= 3:
            reasons.append("chrome_contamination")
        if mode in {ExtractionMode.STATIC_HTML, ExtractionMode.BROWSER_DOM}:
            body_score = float(diagnostics.get("body_score", 0.0))
            chrome_score = float(diagnostics.get("chrome_score", 0.0))
            if body_score < self.thresholds.min_body_score:
                reasons.append("body_score_below_threshold")
            if body_score - chrome_score < self.thresholds.min_body_minus_chrome:
                reasons.append("body_minus_chrome_below_threshold")
        if mode == ExtractionMode.PUBLISHER_MARKDOWN and body_chars < 180:
            reasons.append("publisher_markdown_too_short")
        passed = not reasons
        return QualityReport(
            passed=passed,
            body_chars=body_chars,
            heading_count=heading_count,
            paragraph_count=paragraph_count,
            title_present=title_present,
            code_fence_count=code_count,
            table_count=table_count,
            reasons=reasons,
            comparison={"body_chars": body_chars, "heading_count": heading_count, "paragraph_count": paragraph_count},
        )
