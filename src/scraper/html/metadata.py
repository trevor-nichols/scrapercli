from __future__ import annotations

import json
from typing import Any

from bs4 import BeautifulSoup

from ..models import PageMetadata
from ..utils.text import looks_like_byline, normalize_whitespace
from ..utils.url import absolutize


JSON_LD_AUTHOR_KEYS = ["author", "creator"]
JSON_LD_PUBLISHED_KEYS = ["datePublished", "dateCreated"]
JSON_LD_MODIFIED_KEYS = ["dateModified"]


class MetadataExtractor:
    def extract(self, html: str, source_url: str) -> PageMetadata:
        soup = BeautifulSoup(html, "lxml")
        metadata = PageMetadata(source_url=source_url)
        metadata.title = self._extract_title(soup)
        metadata.canonical_url = self._extract_canonical(soup, source_url)
        metadata.description = self._extract_description(soup)
        metadata.language = self._extract_language(soup)
        metadata.open_graph = self._extract_meta_namespace(soup, "og:")
        metadata.twitter = self._extract_meta_namespace(soup, "twitter:")
        metadata.content_type = self._extract_content_type(soup)
        structured = self._extract_json_ld(soup)
        metadata.structured_metadata = structured
        metadata.author = self._extract_author(soup, structured)
        metadata.published_at = self._extract_date(structured, JSON_LD_PUBLISHED_KEYS)
        metadata.modified_at = self._extract_date(structured, JSON_LD_MODIFIED_KEYS)
        self._extract_article_level_metadata(soup, metadata)
        return metadata

    def _extract_title(self, soup: BeautifulSoup) -> str | None:
        candidates = [
            soup.find("meta", attrs={"property": "og:title"}),
            soup.find("meta", attrs={"name": "twitter:title"}),
            soup.find("title"),
            soup.find("h1"),
        ]
        for candidate in candidates:
            if candidate is None:
                continue
            if candidate.name == "meta":
                content = candidate.get("content")
                if content:
                    return normalize_whitespace(content)
            else:
                text = candidate.get_text(" ", strip=True)
                if text:
                    return normalize_whitespace(text)
        return None

    def _extract_canonical(self, soup: BeautifulSoup, source_url: str) -> str | None:
        link = soup.find("link", rel=lambda value: value and "canonical" in value)
        if link and link.get("href"):
            return absolutize(source_url, link["href"])
        og_url = soup.find("meta", attrs={"property": "og:url"})
        if og_url and og_url.get("content"):
            return absolutize(source_url, og_url["content"])
        return None

    def _extract_description(self, soup: BeautifulSoup) -> str | None:
        candidates = [
            soup.find("meta", attrs={"name": "description"}),
            soup.find("meta", attrs={"property": "og:description"}),
            soup.find("meta", attrs={"name": "twitter:description"}),
        ]
        for candidate in candidates:
            if candidate and candidate.get("content"):
                return normalize_whitespace(candidate["content"])
        return None

    def _extract_language(self, soup: BeautifulSoup) -> str | None:
        html = soup.find("html")
        if html and html.get("lang"):
            return normalize_whitespace(html["lang"])
        return None

    def _extract_content_type(self, soup: BeautifulSoup) -> str | None:
        og_type = soup.find("meta", attrs={"property": "og:type"})
        if og_type and og_type.get("content"):
            return og_type["content"]
        return None

    def _extract_meta_namespace(self, soup: BeautifulSoup, prefix: str) -> dict[str, str]:
        found: dict[str, str] = {}
        for tag in soup.find_all("meta"):
            key = tag.get("property") or tag.get("name")
            if key and key.startswith(prefix) and tag.get("content"):
                found[key] = normalize_whitespace(tag["content"])
        return found

    def _extract_json_ld(self, soup: BeautifulSoup) -> dict[str, Any]:
        payloads: list[Any] = []
        for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
            text = tag.string or tag.get_text(strip=True)
            if not text:
                continue
            try:
                payloads.append(json.loads(text))
            except json.JSONDecodeError:
                continue
        flattened: list[dict[str, Any]] = []
        for payload in payloads:
            if isinstance(payload, dict) and "@graph" in payload and isinstance(payload["@graph"], list):
                flattened.extend([item for item in payload["@graph"] if isinstance(item, dict)])
            elif isinstance(payload, list):
                flattened.extend([item for item in payload if isinstance(item, dict)])
            elif isinstance(payload, dict):
                flattened.append(payload)
        if not flattened:
            return {}
        best = max(flattened, key=self._json_ld_priority)
        return best

    def _json_ld_priority(self, item: dict[str, Any]) -> int:
        score = 0
        type_value = item.get("@type")
        if isinstance(type_value, list):
            types = {str(value).lower() for value in type_value}
        else:
            types = {str(type_value).lower()} if type_value else set()
        if {"article", "newsarticle", "blogposting", "techarticle", "documentationpage"} & types:
            score += 10
        if any(key in item for key in ["headline", "articleBody", "author"]):
            score += 5
        return score

    def _extract_author(self, soup: BeautifulSoup, structured: dict[str, Any]) -> str | None:
        for key in JSON_LD_AUTHOR_KEYS:
            if key not in structured:
                continue
            value = structured[key]
            if isinstance(value, dict):
                if name := value.get("name"):
                    return normalize_whitespace(str(name))
            elif isinstance(value, list):
                names = []
                for item in value:
                    if isinstance(item, dict) and item.get("name"):
                        names.append(normalize_whitespace(str(item["name"])))
                    elif item:
                        names.append(normalize_whitespace(str(item)))
                if names:
                    return ", ".join(dict.fromkeys(names))
            elif value:
                return normalize_whitespace(str(value))
        meta = soup.find("meta", attrs={"name": lambda value: value and value.lower() in {"author", "article:author"}})
        if meta and meta.get("content"):
            return normalize_whitespace(meta["content"])
        article_header = soup.find(["header", "div", "p", "span"], string=lambda value: value and looks_like_byline(str(value)))
        if article_header:
            return normalize_whitespace(article_header.get_text(" ", strip=True))
        return None

    def _extract_date(self, structured: dict[str, Any], keys: list[str]) -> str | None:
        for key in keys:
            if value := structured.get(key):
                return str(value)
        return None

    def _extract_article_level_metadata(self, soup: BeautifulSoup, metadata: PageMetadata) -> None:
        if metadata.author and metadata.published_at and metadata.modified_at:
            return
        article = soup.find("article") or soup.find("main")
        if article is None:
            return
        if not metadata.published_at:
            time_tag = article.find("time")
            if time_tag:
                metadata.published_at = time_tag.get("datetime") or normalize_whitespace(time_tag.get_text(" ", strip=True))
        if not metadata.author:
            possible_bylines = article.find_all(["p", "div", "span", "address"])
            for block in possible_bylines[:8]:
                text = normalize_whitespace(block.get_text(" ", strip=True))
                if looks_like_byline(text):
                    metadata.author = text
                    break
