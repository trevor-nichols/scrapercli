from __future__ import annotations

import xml.etree.ElementTree as ET

from ..http.client import HttpClient
from ..observability.recorder import DecisionRecorder
from ..utils.url import normalize_url, same_host, same_section


class SitemapDiscovery:
    def __init__(self, http_client: HttpClient, recorder: DecisionRecorder) -> None:
        self.http_client = http_client
        self.recorder = recorder

    def gather_urls(
        self,
        sitemap_urls: list[str],
        root_url: str,
        max_urls: int = 1000,
        *,
        max_pages: int | None = None,
    ) -> list[str]:
        limit = max_pages if max_pages is not None else max_urls
        limit = max(limit, 1)
        discovered: list[str] = []
        queue = list(dict.fromkeys(sitemap_urls))
        seen = set(queue)
        while queue and len(discovered) < limit:
            sitemap_url = queue.pop(0)
            snapshot = self.http_client.fetch(sitemap_url, allow_status={404})
            if not snapshot.ok or not snapshot.text:
                continue
            urls, children = parse_sitemap(snapshot.text)
            for child in children:
                if child not in seen:
                    seen.add(child)
                    queue.append(child)
            for url in urls:
                if same_host(root_url, url) and same_section(root_url, url):
                    discovered.append(normalize_url(url))
                if len(discovered) >= limit:
                    break
        return list(dict.fromkeys(discovered))



def parse_sitemap(xml_text: str) -> tuple[list[str], list[str]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return [], []
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}", 1)[0] + "}"
    urls = [loc.text.strip() for loc in root.findall(f".//{ns}url/{ns}loc") if loc.text]
    children = [loc.text.strip() for loc in root.findall(f".//{ns}sitemap/{ns}loc") if loc.text]
    return urls, children
