from __future__ import annotations

import re
from typing import Iterable

import yaml
from bs4 import BeautifulSoup, NavigableString, Tag

from ..models import PageMetadata
from ..utils.text import normalize_whitespace
from ..utils.url import absolutize


BLOCK_TAGS = {
    "article",
    "main",
    "section",
    "div",
    "p",
    "pre",
    "blockquote",
    "ul",
    "ol",
    "li",
    "table",
    "thead",
    "tbody",
    "tr",
    "td",
    "th",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "details",
    "summary",
    "figure",
    "figcaption",
    "dl",
    "dt",
    "dd",
    "hr",
}
SKIP_TAGS = {"script", "style", "noscript", "template"}
ADMONITION_CLASSES = {"admonition", "callout", "note", "warning", "tip", "info", "caution", "danger"}


class MarkdownRenderer:
    def render_html(self, html: str, base_url: str) -> str:
        soup = BeautifulSoup(html, "lxml")
        root = soup.body or soup
        blocks = self._render_children(root, base_url)
        return self._normalize_blocks(blocks)

    def render_node(self, node: Tag, base_url: str) -> str:
        blocks = self._render_block(node, base_url)
        return self._normalize_blocks(blocks)

    def render_text(self, text: str) -> str:
        paragraphs = [normalize_whitespace(block) for block in re.split(r"\n\s*\n", text) if normalize_whitespace(block)]
        return "\n\n".join(paragraphs).strip()

    def _render_children(self, node: Tag, base_url: str) -> list[str]:
        blocks: list[str] = []
        for child in node.children:
            if isinstance(child, NavigableString):
                text = normalize_whitespace(str(child))
                if text:
                    blocks.append(text)
                continue
            if not isinstance(child, Tag):
                continue
            blocks.extend(self._render_block(child, base_url))
        return blocks

    def _render_block(self, node: Tag, base_url: str, list_level: int = 0) -> list[str]:
        name = node.name.lower()
        if name in SKIP_TAGS:
            return []
        if node.has_attr("hidden"):
            return []
        if name == "br":
            return ["  "]
        if self._is_admonition(node):
            return [self._render_admonition(node, base_url)]
        if name in {"main", "article", "section", "div", "figure"}:
            return self._render_children(node, base_url)
        if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            level = int(name[1])
            text = self._render_inline(node, base_url).strip()
            return [f"{'#' * level} {text}"] if text else []
        if name == "p":
            text = self._render_inline(node, base_url).strip()
            return [text] if text else []
        if name == "pre":
            return [self._render_code_block(node)]
        if name == "blockquote":
            child_blocks = self._render_children(node, base_url)
            if not child_blocks:
                text = self._render_inline(node, base_url).strip()
                child_blocks = [text] if text else []
            quoted = []
            for block in child_blocks:
                for line in block.splitlines() or [""]:
                    quoted.append(f"> {line}".rstrip())
            return ["\n".join(quoted).strip()]
        if name in {"ul", "ol"}:
            return self._render_list(node, base_url, ordered=name == "ol", level=list_level)
        if name == "table":
            table = self._render_table(node, base_url)
            return [table] if table else []
        if name == "details":
            summary = node.find("summary")
            title = self._render_inline(summary, base_url).strip() if summary else "Details"
            content_blocks = []
            for child in node.children:
                if child is summary:
                    continue
                if isinstance(child, Tag):
                    content_blocks.extend(self._render_block(child, base_url))
            content = "\n\n".join(content_blocks).strip()
            if content:
                return [f"> **{title}:**\n>\n" + "\n".join(f"> {line}" for line in content.splitlines())]
            return [f"> **{title}:**"]
        if name == "summary":
            text = self._render_inline(node, base_url).strip()
            return [f"**{text}**"] if text else []
        if name == "figcaption":
            text = self._render_inline(node, base_url).strip()
            return [f"_{text}_"] if text else []
        if name == "img":
            src = node.get("src")
            if not src:
                return []
            alt = normalize_whitespace(node.get("alt", "image")) or "image"
            return [f"![{alt}]({absolutize(base_url, src)})"]
        if name == "dl":
            lines: list[str] = []
            for dt in node.find_all("dt", recursive=False):
                term = self._render_inline(dt, base_url).strip()
                dd = dt.find_next_sibling("dd")
                definition = self._render_inline(dd, base_url).strip() if dd else ""
                if term:
                    lines.append(f"- **{term}:** {definition}".strip())
            return ["\n".join(lines)] if lines else []
        if name == "hr":
            return ["---"]
        text = self._render_inline(node, base_url).strip()
        return [text] if text else []

    def _render_inline(self, node: Tag | None, base_url: str) -> str:
        if node is None:
            return ""
        parts: list[str] = []
        for child in node.children:
            if isinstance(child, NavigableString):
                parts.append(escape_markdown(normalize_whitespace(str(child))))
                continue
            if not isinstance(child, Tag):
                continue
            name = child.name.lower()
            if name in SKIP_TAGS:
                continue
            if name == "br":
                parts.append("  \n")
            elif name in {"strong", "b"}:
                parts.append(f"**{self._render_inline(child, base_url)}**")
            elif name in {"em", "i"}:
                parts.append(f"*{self._render_inline(child, base_url)}*")
            elif name == "code" and child.parent and child.parent.name != "pre":
                parts.append(f"`{normalize_whitespace(child.get_text(' ', strip=True))}`")
            elif name == "a":
                text = self._render_inline(child, base_url) or normalize_whitespace(child.get_text(" ", strip=True))
                href = child.get("href")
                if href:
                    parts.append(f"[{text}]({absolutize(base_url, href)})")
                else:
                    parts.append(text)
            elif name == "img":
                src = child.get("src")
                alt = normalize_whitespace(child.get("alt", "image")) or "image"
                if src:
                    parts.append(f"![{alt}]({absolutize(base_url, src)})")
            else:
                parts.append(self._render_inline(child, base_url))
        raw = "".join(parts)
        raw = re.sub(r"\s+\n", "\n", raw)
        raw = re.sub(r"\n\s+", "\n", raw)
        raw = re.sub(r" {2,}", " ", raw)
        return raw.strip()

    def _render_code_block(self, node: Tag) -> str:
        code_tag = node.find("code")
        code_node = code_tag or node
        text = code_node.get_text("\n", strip=False).rstrip("\n")
        language = detect_code_language(code_node)
        fence = "```"
        return f"{fence}{language}\n{text}\n{fence}".strip()

    def _render_list(self, node: Tag, base_url: str, ordered: bool, level: int) -> list[str]:
        lines: list[str] = []
        items = [item for item in node.find_all("li", recursive=False)]
        for idx, item in enumerate(items, start=1):
            marker = f"{idx}." if ordered else "-"
            indent = "  " * level
            child_blocks = []
            inline_chunks: list[str] = []
            for child in item.children:
                if isinstance(child, NavigableString):
                    text = normalize_whitespace(str(child))
                    if text:
                        inline_chunks.append(text)
                elif isinstance(child, Tag):
                    if child.name in {"ul", "ol"}:
                        if inline_chunks:
                            child_blocks.insert(0, "".join(inline_chunks).strip())
                            inline_chunks = []
                        child_blocks.extend(self._render_list(child, base_url, ordered=child.name == "ol", level=level + 1))
                    elif child.name in BLOCK_TAGS and child.name not in {"span", "a", "strong", "em", "code"}:
                        rendered = self._render_block(child, base_url, list_level=level + 1)
                        if rendered:
                            child_blocks.extend(rendered)
                    else:
                        inline_chunks.append(self._render_inline(child, base_url))
            if inline_chunks:
                child_blocks.insert(0, "".join(inline_chunks).strip())
            if not child_blocks:
                continue
            first = child_blocks[0]
            lines.append(f"{indent}{marker} {first}".rstrip())
            for block in child_blocks[1:]:
                for line in block.splitlines():
                    lines.append(f"{indent}  {line}".rstrip())
        return ["\n".join(lines)] if lines else []

    def _render_table(self, node: Tag, base_url: str) -> str:
        rows = []
        for tr in node.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            if not cells:
                continue
            rows.append([normalize_whitespace(self._render_inline(cell, base_url)) for cell in cells])
        if not rows:
            return ""
        width = max(len(row) for row in rows)
        rows = [row + [""] * (width - len(row)) for row in rows]
        header = rows[0]
        separator = ["---"] * width
        body_rows = rows[1:] if len(rows) > 1 else []
        lines = [pipe_join(header), pipe_join(separator)]
        lines.extend(pipe_join(row) for row in body_rows)
        return "\n".join(lines)

    def _is_admonition(self, node: Tag) -> bool:
        classes = {str(value).lower() for value in (node.get("class") or [])}
        return bool(classes & ADMONITION_CLASSES)

    def _render_admonition(self, node: Tag, base_url: str) -> str:
        classes = {str(value).lower() for value in (node.get("class") or [])}
        label = next(iter(classes & ADMONITION_CLASSES), "note").capitalize()
        title_node = None
        for candidate in node.find_all(["p", "div", "span"], recursive=False):
            classes = candidate.get("class") or []
            if any("title" in str(item).lower() for item in classes):
                title_node = candidate
                break
        title = self._render_inline(title_node, base_url).strip() if title_node else label
        blocks = []
        for child in node.children:
            if child is title_node:
                continue
            if isinstance(child, Tag):
                blocks.extend(self._render_block(child, base_url))
        if not blocks:
            text = self._render_inline(node, base_url)
            blocks = [text] if text else []
        quoted = [f"> **{title}**", ">"]
        for block in blocks:
            for line in block.splitlines():
                quoted.append(f"> {line}")
        return "\n".join(quoted).strip()

    def _normalize_blocks(self, blocks: Iterable[str]) -> str:
        cleaned: list[str] = []
        for block in blocks:
            block = normalize_block(block)
            if block:
                cleaned.append(block)
        text = "\n\n".join(cleaned)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


class MarkdownDocumentBuilder:
    def __init__(self, renderer: MarkdownRenderer, include_frontmatter: bool = True) -> None:
        self.renderer = renderer
        self.include_frontmatter = include_frontmatter

    def build(self, metadata: PageMetadata, body_markdown: str, extra_frontmatter: dict[str, str] | None = None) -> str:
        body = body_markdown.strip()
        if metadata.title and not has_equivalent_title_heading(body, metadata.title):
            body = f"# {metadata.title}\n\n{body}".strip()
        if not body:
            body = f"# {metadata.title}" if metadata.title else ""
        frontmatter = self._frontmatter(metadata, extra_frontmatter) if self.include_frontmatter else ""
        return f"{frontmatter}\n\n{body}".strip() if frontmatter else body

    def _frontmatter(self, metadata: PageMetadata, extra: dict[str, str] | None = None) -> str:
        payload = {
            "source_url": metadata.source_url,
            "canonical_url": metadata.canonical_url,
            "title": metadata.title,
            "description": metadata.description,
            "author": metadata.author,
            "published_at": metadata.published_at,
            "modified_at": metadata.modified_at,
            "language": metadata.language,
            "content_type": metadata.content_type,
        }
        if extra:
            payload.update(extra)
        compact = {key: value for key, value in payload.items() if value not in (None, "", {}, [])}
        if not compact:
            return ""
        serialized = yaml.safe_dump(compact, sort_keys=True, allow_unicode=True).strip()
        return f"---\n{serialized}\n---"



def normalize_block(block: str) -> str:
    block = block.rstrip()
    if block.startswith("```"):
        return block.strip()
    lines = [re.sub(r"\s+", " ", line).rstrip() for line in block.splitlines()]
    return "\n".join(line for line in lines).strip()



def detect_code_language(node: Tag) -> str:
    candidates = []
    classes = node.get("class") or []
    candidates.extend(classes)
    parent = node.parent if isinstance(node.parent, Tag) else None
    if parent is not None:
        candidates.extend(parent.get("class") or [])
    for item in candidates:
        lowered = str(item).lower()
        if lowered.startswith("language-"):
            return lowered.split("language-", 1)[1]
        if lowered.startswith("lang-"):
            return lowered.split("lang-", 1)[1]
    return ""



def pipe_join(cells: list[str]) -> str:
    escaped = [cell.replace("|", "\\|") for cell in cells]
    return "| " + " | ".join(escaped) + " |"



def escape_markdown(text: str) -> str:
    text = text.replace("\\", "\\\\")
    text = text.replace("*", "\\*")
    text = text.replace("_", "\\_")
    return text



def has_equivalent_title_heading(markdown: str, title: str) -> bool:
    title_norm = normalize_whitespace(title).lower()
    for line in markdown.splitlines():
        if not line.startswith("#"):
            continue
        heading = normalize_whitespace(line.lstrip("# ")).lower()
        if heading == title_norm:
            return True
        title_tokens = {token for token in title_norm.split() if len(token) > 2}
        heading_tokens = {token for token in heading.split() if len(token) > 2}
        if title_tokens and len(title_tokens & heading_tokens) >= max(2, len(title_tokens) // 2):
            return True
        break
    return False
