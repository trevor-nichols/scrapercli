from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from ..models import HTMLExtractionDiagnostics, NodeFeatureSet, NodeScore
from ..utils.text import keyword_hits, link_density, looks_like_byline, normalize_whitespace, sentence_like
from .repetition import RepetitionIndex, depth, node_signature


CANDIDATE_TAGS = ["main", "article", "section", "div", "aside", "nav", "header", "footer"]
NEGATIVE_TOP_LEVEL_TAGS = {"nav", "footer", "aside", "header"}
NEGATIVE_TOP_LEVEL_ROLES = {"navigation", "contentinfo", "complementary", "banner"}
SOCIAL_TERMS = {"facebook", "linkedin", "twitter", "x.com", "youtube", "github", "instagram", "share"}


@dataclass
class ScoredNode:
    node: Tag
    score: NodeScore


class HTMLScorer:
    def __init__(self, repetition_index: RepetitionIndex) -> None:
        self.repetition_index = repetition_index

    def score(self, url: str, html: str, title: str | None = None) -> tuple[list[ScoredNode], HTMLExtractionDiagnostics]:
        soup = BeautifulSoup(html, "lxml")
        candidates = [node for node in soup.find_all(CANDIDATE_TAGS) if isinstance(node, Tag)]
        host = urlparse(url).netloc
        total = max(1, len(candidates))
        scored_nodes: list[ScoredNode] = []
        for index, node in enumerate(candidates):
            features = self._features_for_node(node, index, total, title, host)
            score = self._score_node(node, features)
            scored_nodes.append(ScoredNode(node=node, score=score))
        diagnostics = HTMLExtractionDiagnostics(node_scores=[item.score for item in scored_nodes])
        winner = self.choose_winner(scored_nodes)
        if winner is not None:
            diagnostics.winner_xpath = winner.score.xpath_like
            diagnostics.body_score = winner.score.body_score
            diagnostics.chrome_score = winner.score.chrome_score
            diagnostics.metadata_preserve_score = winner.score.metadata_preserve_score
            diagnostics.paragraph_count = winner.score.features.paragraph_count
            diagnostics.body_chars = winner.score.features.text_chars
            if winner.score.features.text_chars < 300:
                diagnostics.signals.append("thin_body_candidate")
            if winner.score.features.link_density >= 0.65:
                diagnostics.signals.append("high_link_density")
            if winner.score.features.repetition_score >= 0.71:
                diagnostics.signals.append("high_repetition")
        return scored_nodes, diagnostics

    def choose_winner(self, scored_nodes: list[ScoredNode]) -> ScoredNode | None:
        if not scored_nodes:
            return None
        keepers = [item for item in scored_nodes if item.score.keep_in_body]
        pool = keepers or scored_nodes
        pool.sort(
            key=lambda item: (
                item.score.body_score,
                item.score.body_score - item.score.chrome_score,
                item.score.features.text_chars,
                -item.score.features.link_density,
            ),
            reverse=True,
        )
        winner = pool[0]
        parent = winner.node.find_parent(["article", "main"])
        if isinstance(parent, Tag):
            for item in pool[1:6]:
                if item.node is parent and item.score.body_score >= winner.score.body_score * 0.85:
                    return item
        return winner

    def should_keep_sibling(self, winner: ScoredNode, candidate: ScoredNode) -> bool:
        if candidate.node is winner.node:
            return True
        if candidate.score.drop_as_chrome:
            return False
        if candidate.score.metadata_preserve_score >= 20:
            return True
        if candidate.score.body_score >= winner.score.body_score * 0.4 and (candidate.score.body_score - candidate.score.chrome_score) >= 0:
            return True
        return False

    def _features_for_node(self, node: Tag, index: int, total: int, title: str | None, host: str) -> NodeFeatureSet:
        text = normalize_whitespace(node.get_text(" ", strip=True))
        text_chars = len(text)
        linked_text_chars = sum(len(normalize_whitespace(anchor.get_text(" ", strip=True))) for anchor in node.find_all("a"))
        paragraphs = [normalize_whitespace(p.get_text(" ", strip=True)) for p in node.find_all("p")]
        paragraphs = [paragraph for paragraph in paragraphs if paragraph]
        heading_count = len(node.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]))
        has_h1_or_h2 = node.find(["h1", "h2"]) is not None
        byline = self._has_time_or_byline(node)
        code_blocks = len(node.find_all("pre"))
        tables = len(node.find_all("table"))
        lists = len(node.find_all(["ul", "ol"]))
        blockquotes = len(node.find_all("blockquote"))
        form_controls = len(node.find_all(["input", "select", "textarea", "form"]))
        buttons = len(node.find_all("button"))
        relative_position = index / max(1, total - 1) if total > 1 else 0.5
        landmark = node.get("role") or node.name
        signature = node_signature(node)
        repetition_score = self.repetition_index.score(host, signature)
        near_title = self._near_title(node, title)
        nested_inside_article_or_main = node.find_parent(["article", "main"]) is not None
        return NodeFeatureSet(
            xpath_like=xpath_like(node),
            tag=node.name,
            text_chars=text_chars,
            linked_text_chars=linked_text_chars,
            link_density=link_density(text_chars, linked_text_chars),
            paragraph_count=len(paragraphs),
            avg_paragraph_length=round(sum(len(paragraph) for paragraph in paragraphs) / max(1, len(paragraphs)), 2),
            heading_count=heading_count,
            has_h1_or_h2=has_h1_or_h2,
            has_time_or_byline=byline,
            code_blocks=code_blocks,
            tables=tables,
            lists=lists,
            blockquotes=blockquotes,
            form_controls=form_controls,
            buttons=buttons,
            dom_depth=depth(node),
            relative_position=relative_position,
            landmark=landmark,
            repetition_score=repetition_score,
            keyword_hits=keyword_hits(text),
            near_title=near_title,
            nested_inside_article_or_main=nested_inside_article_or_main,
        )

    def _score_node(self, node: Tag, features: NodeFeatureSet) -> NodeScore:
        body_score = 0.0
        chrome_score = 0.0
        metadata_score = 0.0
        reasons: list[str] = []
        role = (node.get("role") or "").lower()
        top_level_negative = self._is_top_level_negative_landmark(node)
        anchor_heavy = self._is_anchor_heavy(node)
        has_rich_content = features.code_blocks + features.tables + features.lists + features.blockquotes > 0
        keyword_cluster = len(features.keyword_hits) >= 2
        social_cluster = self._has_social_cluster(node)
        long_paragraph_text = features.avg_paragraph_length >= 120
        short_structured_block = 20 <= features.text_chars <= 250
        tag_metadata_block = self._has_tag_metadata(node)

        if node.name == "main" or role == "main":
            body_score += 25
            reasons.append("body:+25 main landmark")
        if node.name == "article" or role == "article":
            body_score += 22
            reasons.append("body:+22 article landmark")
        if features.nested_inside_article_or_main:
            body_score += 10
            reasons.append("body:+10 descendant_of_main_or_article")
        if features.heading_count >= 1 and features.paragraph_count >= 2:
            body_score += 8
            reasons.append("body:+8 heading_followed_by_paragraph_cluster")
        if features.text_chars >= 800:
            body_score += 8
            reasons.append("body:+8 text_len>=800")
        elif 300 <= features.text_chars <= 799:
            body_score += 4
            reasons.append("body:+4 text_len>=300")
        if features.paragraph_count >= 3:
            body_score += 6
            reasons.append("body:+6 paragraph_count>=3")
        if features.avg_paragraph_length >= 120:
            body_score += 6
            reasons.append("body:+6 avg_paragraph_length>=120")
        if features.link_density <= 0.20:
            body_score += 6
            reasons.append("body:+6 low_link_density")
        if has_rich_content:
            body_score += 8
            reasons.append("body:+8 rich_structured_content")
        if features.near_title:
            body_score += 6
            reasons.append("body:+6 near_title")
        if 0.2 <= features.relative_position <= 0.8:
            body_score += 4
            reasons.append("body:+4 middle_document_placement")
        if top_level_negative:
            body_score -= 20
            reasons.append("body:-20 top_level_negative_landmark")
        if features.link_density >= 0.65:
            body_score -= 16
            reasons.append("body:-16 high_link_density")
        if anchor_heavy:
            body_score -= 10
            reasons.append("body:-10 anchor_heavy")
        if features.form_controls + features.buttons >= 4:
            body_score -= 12
            reasons.append("body:-12 form_or_button_heavy")
        if features.repetition_score >= 0.71:
            body_score -= 12
            reasons.append("body:-12 high_repetition")
        if keyword_cluster:
            body_score -= 8
            reasons.append("body:-8 boilerplate_keyword_cluster")
        if features.text_chars < 120 and not features.has_time_or_byline:
            body_score -= 6
            reasons.append("body:-6 very_short_without_metadata")

        if node.name == "nav" or role == "navigation":
            chrome_score += 35
            reasons.append("chrome:+35 top_level_nav")
        if node.name == "footer" or role == "contentinfo":
            chrome_score += 30
            reasons.append("chrome:+30 top_level_footer")
        if node.name == "header" or role == "banner":
            chrome_score += 24
            reasons.append("chrome:+24 top_level_header")
        if node.name == "aside" or role == "complementary":
            chrome_score += 20
            reasons.append("chrome:+20 aside")
        if features.link_density >= 0.65:
            chrome_score += 18
            reasons.append("chrome:+18 high_link_density")
        if features.repetition_score >= 0.71:
            chrome_score += 16
            reasons.append("chrome:+16 high_repetition")
        if keyword_cluster:
            chrome_score += 10
            reasons.append("chrome:+10 boilerplate_keywords")
        if social_cluster:
            chrome_score += 8
            reasons.append("chrome:+8 social_cluster")
        if features.form_controls >= 1 or features.buttons >= 3:
            chrome_score += 8
            reasons.append("chrome:+8 form_search_newsletter")
        if features.relative_position <= 0.1 or features.relative_position >= 0.9:
            chrome_score += 6
            reasons.append("chrome:+6 extreme_page_position")
        if features.nested_inside_article_or_main and features.paragraph_count >= 2 and sentence_like(node.get_text(" ", strip=True)):
            chrome_score -= 15
            reasons.append("chrome:-15 nested_prose_inside_main_or_article")
        if features.near_title or features.has_time_or_byline:
            chrome_score -= 10
            reasons.append("chrome:-10 adjacent_to_title_or_byline")
        if long_paragraph_text:
            chrome_score -= 10
            reasons.append("chrome:-10 long_paragraph_text")

        if node.name in {"header", "footer"} and node.find_parent(["article", "section", "main"]) is not None:
            metadata_score += 24
            reasons.append("meta:+24 nested_header_or_footer_inside_content")
        if features.has_time_or_byline:
            metadata_score += 18
            reasons.append("meta:+18 time_or_byline_signal")
        if features.near_title:
            metadata_score += 16
            reasons.append("meta:+16 near_title")
        if short_structured_block:
            metadata_score += 10
            reasons.append("meta:+10 short_structured_block")
        if tag_metadata_block:
            metadata_score += 8
            reasons.append("meta:+8 tag_or_category_metadata")
        if features.repetition_score <= 0.30:
            metadata_score += 6
            reasons.append("meta:+6 low_repetition")
        if node.name == "footer" and self._is_top_level(node):
            metadata_score -= 20
            reasons.append("meta:-20 top_level_footer")
        if features.repetition_score >= 0.71:
            metadata_score -= 12
            reasons.append("meta:-12 high_repetition")
        if features.link_density >= 0.65 and features.text_chars - features.linked_text_chars < 80:
            metadata_score -= 10
            reasons.append("meta:-10 link_heavy_little_non_link_text")

        keep = body_score >= 25 and (body_score - chrome_score) >= 10
        drop = chrome_score >= 30 and metadata_score < 20
        preserve = metadata_score >= 20 and body_score < 25
        return NodeScore(
            xpath_like=features.xpath_like,
            tag=node.name,
            body_score=round(body_score, 2),
            chrome_score=round(chrome_score, 2),
            metadata_preserve_score=round(metadata_score, 2),
            keep_in_body=keep,
            drop_as_chrome=drop,
            preserve_as_metadata=preserve,
            features=features,
            reasons=reasons,
        )

    def _is_top_level_negative_landmark(self, node: Tag) -> bool:
        role = (node.get("role") or "").lower()
        return self._is_top_level(node) and (node.name in NEGATIVE_TOP_LEVEL_TAGS or role in NEGATIVE_TOP_LEVEL_ROLES)

    def _is_top_level(self, node: Tag) -> bool:
        return node.find_parent(["main", "article", "section"]) is None

    def _has_time_or_byline(self, node: Tag) -> bool:
        if node.find(["time", "address"]):
            return True
        text = normalize_whitespace(node.get_text(" ", strip=True))
        return looks_like_byline(text)

    def _near_title(self, node: Tag, title: str | None) -> bool:
        if not title:
            return False
        title_norm = normalize_whitespace(title).lower()
        if not title_norm:
            return False
        node_text = normalize_whitespace(node.get_text(" ", strip=True))[:400].lower()
        if title_norm in node_text:
            return True
        title_tokens = [token for token in title_norm.split() if len(token) > 2]
        overlap = sum(1 for token in title_tokens if token in node_text)
        return overlap >= max(2, len(title_tokens) // 2)

    def _is_anchor_heavy(self, node: Tag) -> bool:
        anchors = node.find_all("a")
        if len(anchors) < 5:
            return False
        lengths = [len(normalize_whitespace(anchor.get_text(" ", strip=True))) for anchor in anchors]
        lengths = [value for value in lengths if value > 0]
        if not lengths:
            return False
        return sum(lengths) / len(lengths) < 18

    def _has_social_cluster(self, node: Tag) -> bool:
        labels = []
        for anchor in node.find_all("a")[:12]:
            label = normalize_whitespace(anchor.get_text(" ", strip=True) or anchor.get("aria-label", ""))
            if label:
                labels.append(label.lower())
        if not labels:
            return False
        hits = sum(1 for label in labels if any(term in label for term in SOCIAL_TERMS))
        return hits >= 2

    def _has_tag_metadata(self, node: Tag) -> bool:
        text = normalize_whitespace(node.get_text(" ", strip=True)).lower()
        return any(token in text for token in ["tags", "tag", "categories", "category", "topics"])



def xpath_like(node: Tag) -> str:
    segments: list[str] = []
    current: Tag | None = node
    while current is not None and isinstance(current, Tag):
        parent = current.parent if isinstance(current.parent, Tag) else None
        index = 1
        if parent is not None:
            siblings = [sib for sib in parent.find_all(current.name, recursive=False)]
            try:
                index = siblings.index(current) + 1
            except ValueError:
                index = 1
        segments.append(f"{current.name}[{index}]")
        current = parent
    return "/" + "/".join(reversed(segments))
