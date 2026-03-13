from __future__ import annotations

import json
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ..models import CandidateKind, CandidateSource, DiscoveryBundle, FrameworkFamily
from .base import BaseAdapter, DocsPruningAdapter


class NextJsAdapter(BaseAdapter):
    framework_family = FrameworkFamily.NEXTJS

    def augment_candidates(self, bundle: DiscoveryBundle) -> list[CandidateSource]:
        page = bundle.page
        if not page or not page.text:
            return []
        soup = BeautifulSoup(page.text, "lxml")
        script = soup.find(id="__NEXT_DATA__")
        if not script:
            return []
        try:
            payload = json.loads(script.get_text(strip=True))
        except json.JSONDecodeError:
            return []
        build_id = payload.get("buildId")
        if not build_id:
            return []
        parsed = urlparse(bundle.normalized_url)
        path = parsed.path.strip("/") or "index"
        if path.endswith(".html"):
            path = path[:-5]
        data_url = f"{parsed.scheme}://{parsed.netloc}/_next/data/{build_id}/{path}.json"
        return [
            CandidateSource(
                kind=CandidateKind.API_ENDPOINT,
                url=data_url,
                method="GET",
                confidence=0.82,
                cost=3,
                evidence=["next_build_id_detected", "constructed_next_data_route"],
                metadata={"source": "nextjs_adapter"},
            )
        ]


class DocusaurusAdapter(DocsPruningAdapter):
    framework_family = FrameworkFamily.DOCUSAURUS
    DROP_CLASS_FRAGMENTS = (
        "theme-doc-sidebar",
        "table-of-contents",
        "theme-edit-this-page",
        "theme-doc-version-badge",
        "breadcrumbs",
    )


class VitePressAdapter(DocsPruningAdapter):
    framework_family = FrameworkFamily.VITEPRESS
    DROP_CLASS_FRAGMENTS = (
        "VPNav",
        "VPSidebar",
        "VPDocAside",
        "VPDocFooter",
        "VPFooter",
        "pager-link",
    )


class MintlifyAdapter(DocsPruningAdapter):
    framework_family = FrameworkFamily.MINTLIFY
    DROP_CLASS_FRAGMENTS = (
        "sidebar",
        "toc",
        "topbar",
        "navbar",
        "breadcrumbs",
    )


class AdapterRegistry:
    def __init__(self) -> None:
        self.adapters: dict[FrameworkFamily, BaseAdapter] = {
            FrameworkFamily.NEXTJS: NextJsAdapter(),
            FrameworkFamily.DOCUSAURUS: DocusaurusAdapter(),
            FrameworkFamily.VITEPRESS: VitePressAdapter(),
            FrameworkFamily.MINTLIFY: MintlifyAdapter(),
        }
        self.default = BaseAdapter()

    def for_framework(self, family: FrameworkFamily) -> BaseAdapter:
        return self.adapters.get(family, self.default)
