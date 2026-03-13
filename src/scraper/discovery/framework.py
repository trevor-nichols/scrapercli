from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from bs4 import BeautifulSoup

from ..models import FrameworkFamily, FrameworkHint


@dataclass
class DetectorResult:
    family: FrameworkFamily
    confidence: float
    evidence: list[str]
    strategy: str
    sources: list[str]


class FrameworkDetectorRegistry:
    def __init__(self) -> None:
        self.detectors: list[Callable[[str, BeautifulSoup], DetectorResult | None]] = [
            self._mintlify,
            self._nextjs,
            self._astro,
            self._docusaurus,
            self._vitepress,
            self._generic_static,
            self._generic_app_shell,
        ]

    def detect(self, html: str, final_url: str) -> FrameworkHint:
        soup = BeautifulSoup(html, "lxml")
        results = [result for detector in self.detectors if (result := detector(final_url, soup)) is not None]
        if not results:
            return FrameworkHint()
        results.sort(key=lambda item: item.confidence, reverse=True)
        best = results[0]
        return FrameworkHint(
            framework_family=best.family,
            confidence_score=round(best.confidence, 3),
            evidence=best.evidence,
            suggested_extraction_strategy=best.strategy,
            suggested_content_sources=best.sources,
        )

    def _nextjs(self, _: str, soup: BeautifulSoup) -> DetectorResult | None:
        evidence: list[str] = []
        confidence = 0.0
        if soup.find(src=lambda value: value and "/_next/" in value):
            confidence += 0.55
            evidence.append("next_asset_namespace:/_next/")
        if soup.find(id="__NEXT_DATA__"):
            confidence += 0.35
            evidence.append("next_inline_data:__NEXT_DATA__")
        if soup.find(string=lambda value: value and "self.__next_f.push" in value):
            confidence += 0.25
            evidence.append("next_app_router_stream")
        if confidence <= 0:
            return None
        return DetectorResult(
            family=FrameworkFamily.NEXTJS,
            confidence=min(confidence, 0.99),
            evidence=evidence,
            strategy="prefer_embedded_json_then_html",
            sources=["__NEXT_DATA__", "_next/data JSON", "server-rendered HTML"],
        )

    def _astro(self, _: str, soup: BeautifulSoup) -> DetectorResult | None:
        evidence: list[str] = []
        confidence = 0.0
        generator = soup.find("meta", attrs={"name": "generator"})
        if generator and generator.get("content") and "astro" in generator["content"].lower():
            confidence += 0.45
            evidence.append("generator:astro")
        if soup.find(src=lambda value: value and "/_astro/" in value):
            confidence += 0.4
            evidence.append("astro_asset_namespace:/_astro/")
        if confidence <= 0:
            return None
        return DetectorResult(
            family=FrameworkFamily.ASTRO,
            confidence=min(confidence, 0.95),
            evidence=evidence,
            strategy="prefer_static_html",
            sources=["static HTML", "isolated island payloads"],
        )

    def _docusaurus(self, final_url: str, soup: BeautifulSoup) -> DetectorResult | None:
        evidence: list[str] = []
        confidence = 0.0
        generator = soup.find("meta", attrs={"name": "generator"})
        if generator and generator.get("content") and "docusaurus" in generator["content"].lower():
            confidence += 0.6
            evidence.append("generator:docusaurus")
        if soup.find(attrs={"class": lambda value: value and "theme-doc-markdown" in (" ".join(value) if isinstance(value, list) else str(value))}):
            confidence += 0.25
            evidence.append("docusaurus_theme_doc_markdown")
        if "/docs/" in final_url or "/blog/" in final_url:
            confidence += 0.1
            evidence.append("docs_or_blog_path")
        if confidence <= 0.15:
            return None
        return DetectorResult(
            family=FrameworkFamily.DOCUSAURUS,
            confidence=min(confidence, 0.93),
            evidence=evidence,
            strategy="prefer_static_html_docs_pruning",
            sources=["static HTML", "MDX-rendered content"],
        )

    def _vitepress(self, _: str, soup: BeautifulSoup) -> DetectorResult | None:
        evidence: list[str] = []
        confidence = 0.0
        generator = soup.find("meta", attrs={"name": "generator"})
        if generator and generator.get("content") and "vitepress" in generator["content"].lower():
            confidence += 0.55
            evidence.append("generator:vitepress")
        if soup.find(attrs={"class": lambda value: value and "VPContent" in (" ".join(value) if isinstance(value, list) else str(value))}):
            confidence += 0.3
            evidence.append("vitepress_vpcontent_class")
        if confidence <= 0:
            return None
        return DetectorResult(
            family=FrameworkFamily.VITEPRESS,
            confidence=min(confidence, 0.9),
            evidence=evidence,
            strategy="prefer_static_html_then_serialized_data",
            sources=["static HTML", "serialized page data"],
        )

    def _mintlify(self, _: str, soup: BeautifulSoup) -> DetectorResult | None:
        evidence: list[str] = []
        confidence = 0.0
        if soup.find(string=lambda value: value and "mintlify" in value.lower()):
            confidence += 0.25
            evidence.append("mintlify_text_marker")
        if soup.find("a", href=lambda value: value and value.endswith(".md")):
            confidence += 0.25
            evidence.append("linked_markdown_present")
        if soup.find(src=lambda value: value and "mintlify" in value.lower()):
            confidence += 0.45
            evidence.append("mintlify_asset_marker")
        if confidence <= 0:
            return None
        return DetectorResult(
            family=FrameworkFamily.MINTLIFY,
            confidence=min(confidence, 0.9),
            evidence=evidence,
            strategy="prefer_llms_and_markdown_twins",
            sources=["llms.txt", "page-level .md", "static HTML"],
        )

    def _generic_static(self, _: str, soup: BeautifulSoup) -> DetectorResult | None:
        body = soup.body
        if body is None:
            return None
        body_text = body.get_text(" ", strip=True)
        script_count = len(soup.find_all("script"))
        confidence = 0.0
        evidence: list[str] = []
        if len(body_text) > 1200:
            confidence += 0.45
            evidence.append("substantial_body_text")
        if soup.find(["main", "article"]):
            confidence += 0.25
            evidence.append("semantic_main_or_article")
        if script_count <= 12:
            confidence += 0.15
            evidence.append("low_script_weight")
        if confidence <= 0.2:
            return None
        return DetectorResult(
            family=FrameworkFamily.GENERIC_STATIC,
            confidence=min(confidence, 0.85),
            evidence=evidence,
            strategy="prefer_static_html",
            sources=["static HTML"],
        )

    def _generic_app_shell(self, _: str, soup: BeautifulSoup) -> DetectorResult | None:
        body = soup.body
        if body is None:
            return None
        body_text = body.get_text(" ", strip=True)
        script_count = len(soup.find_all("script"))
        root_containers = [
            tag
            for tag in soup.find_all(["div", "main"], recursive=False)
            if tag.get("id") in {"root", "__next", "app", "__nuxt"} or (tag.get("id") and "root" in tag.get("id", ""))
        ]
        confidence = 0.0
        evidence: list[str] = []
        if len(body_text) < 400:
            confidence += 0.35
            evidence.append("thin_body_text")
        if script_count >= 15:
            confidence += 0.25
            evidence.append("high_script_weight")
        if root_containers:
            confidence += 0.25
            evidence.append("app_shell_root_container")
        if soup.find(string=lambda value: value and any(token in value for token in ["hydrateRoot", "ReactDOM", "__NUXT__", "ApolloClient"])):
            confidence += 0.15
            evidence.append("client_bootstrap_marker")
        if confidence <= 0.25:
            return None
        return DetectorResult(
            family=FrameworkFamily.GENERIC_APP_SHELL,
            confidence=min(confidence, 0.85),
            evidence=evidence,
            strategy="inspect_inline_state_then_http_replay",
            sources=["hydration payloads", "API endpoints", "browser discovery fallback"],
        )
