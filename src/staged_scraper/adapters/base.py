from __future__ import annotations

from bs4 import BeautifulSoup

from ..models import CandidateSource, DiscoveryBundle, FrameworkFamily


class BaseAdapter:
    framework_family: FrameworkFamily = FrameworkFamily.UNKNOWN

    def augment_candidates(self, bundle: DiscoveryBundle) -> list[CandidateSource]:
        return []

    def preprocess_html(self, html: str) -> str:
        return html


class DocsPruningAdapter(BaseAdapter):
    DROP_CLASS_FRAGMENTS: tuple[str, ...] = ()

    def preprocess_html(self, html: str) -> str:
        soup = BeautifulSoup(html, "lxml")
        for fragment in self.DROP_CLASS_FRAGMENTS:
            for node in soup.find_all(attrs={"class": lambda value: _class_contains(value, fragment)}):
                node.decompose()
        return str(soup)



def _class_contains(value: str | list[str] | None, fragment: str) -> bool:
    if value is None:
        return False
    if isinstance(value, list):
        haystack = " ".join(str(item) for item in value)
    else:
        haystack = str(value)
    return fragment in haystack
