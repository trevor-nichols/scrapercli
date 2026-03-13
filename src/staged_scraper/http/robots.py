from __future__ import annotations

import re
from urllib import robotparser

from ..models import FetchSnapshot, RobotsInfo
from ..utils.url import site_root


SITEMAP_RE = re.compile(r"^\s*Sitemap\s*:\s*(?P<url>\S+)", re.I | re.M)


class RobotsPolicy:
    def __init__(self, user_agent: str) -> None:
        self.user_agent = user_agent
        self.parsers: dict[str, robotparser.RobotFileParser] = {}
        self.cache: dict[str, RobotsInfo] = {}

    def register(self, snapshot: FetchSnapshot) -> RobotsInfo:
        text = snapshot.text or ""
        url = snapshot.final_url or snapshot.url
        root = site_root(url)
        parser = robotparser.RobotFileParser()
        parser.set_url(url)
        parser.parse(text.splitlines())
        self.parsers[root] = parser
        info = RobotsInfo(url=url, text=text, allowed=True, sitemaps=self.extract_sitemaps(text))
        self.cache[root] = info
        return info

    def can_fetch(self, target_url: str) -> bool:
        root = site_root(target_url)
        parser = self.parsers.get(root)
        if parser is None:
            return True
        try:
            return parser.can_fetch(self.user_agent, target_url)
        except Exception:
            return True

    @staticmethod
    def extract_sitemaps(text: str) -> list[str]:
        return [match.group("url") for match in SITEMAP_RE.finditer(text)]
