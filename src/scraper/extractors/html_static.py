from __future__ import annotations

import time

from bs4 import BeautifulSoup, Tag

from ..adapters import AdapterRegistry
from ..html.markdown import MarkdownDocumentBuilder, MarkdownRenderer
from ..html.repetition import RepetitionIndex
from ..html.scoring import HTMLScorer, ScoredNode
from ..models import ContentKind, DiscoveryBundle, ExtractionAttempt, ExtractionMode, MarkdownDocument, PageMetadata
from ..observability.recorder import DecisionRecorder


class StaticHTMLExtractor:
    mode_name = ExtractionMode.STATIC_HTML

    def __init__(self, recorder: DecisionRecorder, repetition_index: RepetitionIndex, include_frontmatter: bool = True) -> None:
        self.recorder = recorder
        self.repetition_index = repetition_index
        self.scorer = HTMLScorer(repetition_index)
        self.renderer = MarkdownRenderer()
        self.builder = MarkdownDocumentBuilder(self.renderer, include_frontmatter=include_frontmatter)
        self.adapters = AdapterRegistry()

    def run(self, bundle: DiscoveryBundle) -> ExtractionAttempt:
        start = time.perf_counter()
        attempt = ExtractionAttempt(mode=self.mode_name, url=bundle.normalized_url)
        page = bundle.page
        if not page or not page.text or not page.is_html:
            attempt.outcome = "no_html_page"
            attempt.observed_signals.append("html_unavailable")
            attempt.elapsed_ms = int((time.perf_counter() - start) * 1000)
            return attempt
        adapter = self.adapters.for_framework(bundle.framework_hint.framework_family)
        prepared_html = prepare_html_for_scoring(adapter.preprocess_html(page.text))
        scored_nodes, diagnostics = self.scorer.score(page.final_url, prepared_html, title=bundle.metadata.title if bundle.metadata else None)
        winner = self.scorer.choose_winner(scored_nodes)
        if winner is None:
            attempt.outcome = "no_body_winner"
            attempt.observed_signals.append("body_scoring_failed")
            attempt.elapsed_ms = int((time.perf_counter() - start) * 1000)
            return attempt
        rendered_html = render_selected_nodes(prepared_html, winner, scored_nodes, self.scorer)
        metadata = bundle.metadata.model_copy(deep=True) if bundle.metadata else PageMetadata(source_url=page.final_url, canonical_url=page.final_url)
        markdown_body = self.renderer.render_html(rendered_html, metadata.canonical_url or page.final_url)
        markdown = self.builder.build(metadata, markdown_body, extra_frontmatter={"extraction_method": self.mode_name.value, "source_kind": "html_page", "body_score": f"{diagnostics.body_score:.2f}", "chrome_score": f"{diagnostics.chrome_score:.2f}"})
        attempt.success = True
        attempt.document = MarkdownDocument(markdown=markdown, metadata=metadata, content_kind=ContentKind.HTML, diagnostics={"winner_xpath": diagnostics.winner_xpath, "body_score": diagnostics.body_score, "chrome_score": diagnostics.chrome_score, "metadata_preserve_score": diagnostics.metadata_preserve_score, "body_chars": diagnostics.body_chars, "signals": diagnostics.signals, "top_candidates": [node.score.model_dump(mode="python") for node in scored_nodes[:10]]})
        attempt.outcome = "static_html_selected"
        attempt.observed_signals.extend(diagnostics.signals)
        attempt.elapsed_ms = int((time.perf_counter() - start) * 1000)
        return attempt



def prepare_html_for_scoring(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for node in soup.find_all(["script", "style", "noscript", "template"]):
        node.decompose()
    for node in soup.find_all(attrs={"hidden": True}):
        node.decompose()
    for node in soup.find_all(attrs={"aria-hidden": "true"}):
        text = node.get_text(" ", strip=True)
        if len(text) <= 6 and not node.find(["img", "svg"]):
            node.decompose()
    return str(soup)



def render_selected_nodes(html: str, winner: ScoredNode, scored_nodes: list[ScoredNode], scorer: HTMLScorer) -> str:
    soup = BeautifulSoup(html, "lxml")
    node_map = {item.score.xpath_like: item for item in scored_nodes}
    winner_clone = find_by_xpath_like(soup, winner.score.xpath_like)
    if winner_clone is None:
        return str(soup)
    fragments: list[str] = []
    parent = winner_clone.parent if isinstance(winner_clone.parent, Tag) else None
    siblings = []
    if parent is not None:
        for child in parent.find_all(recursive=False):
            if not isinstance(child, Tag):
                continue
            xpath = xpath_like_runtime(child)
            if xpath in node_map and scorer.should_keep_sibling(winner, node_map[xpath]):
                siblings.append(child)
    else:
        siblings = [winner_clone]
    if not siblings:
        siblings = [winner_clone]
    for node in siblings:
        cleaned = prune_descendant_chrome(node)
        fragments.append(str(cleaned))
    return "\n".join(fragments)



def prune_descendant_chrome(node: Tag) -> Tag:
    clone = BeautifulSoup(str(node), "lxml")
    root = clone.body.contents[0] if clone.body and clone.body.contents else clone
    target = root if isinstance(root, Tag) else clone
    for bad in target.find_all(["nav", "aside", "form"]):
        bad.decompose()
    for footer in target.find_all("footer"):
        if footer.find_parent("article") is None:
            footer.decompose()
    for header in target.find_all("header"):
        if header.find_parent("article") is None and header.find_parent("section") is None:
            if header.find_all("a") and len(header.get_text(" ", strip=True)) < 200:
                header.decompose()
    return target



def find_by_xpath_like(soup: BeautifulSoup, xpath: str) -> Tag | None:
    segments = [segment for segment in xpath.strip("/").split("/") if segment]
    current: Tag | BeautifulSoup = soup
    if segments and segments[0].startswith("[document]"):
        segments = segments[1:]
    for segment in segments:
        if "[" in segment and segment.endswith("]"):
            name, index_raw = segment[:-1].split("[")
            index = int(index_raw)
        else:
            name, index = segment, 1
        candidates = [child for child in current.find_all(name, recursive=False)]
        if len(candidates) < index or index <= 0:
            return None
        current = candidates[index - 1]
    return current if isinstance(current, Tag) else None



def xpath_like_runtime(node: Tag) -> str:
    segments: list[str] = []
    current: Tag | None = node
    while current is not None and isinstance(current, Tag):
        parent = current.parent if isinstance(current.parent, Tag) else None
        siblings = [sib for sib in parent.find_all(current.name, recursive=False)] if parent is not None else [current]
        try:
            index = siblings.index(current) + 1
        except ValueError:
            index = 1
        segments.append(f"{current.name}[{index}]")
        current = parent
    return "/" + "/".join(reversed(segments))
