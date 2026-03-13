from __future__ import annotations

from bs4 import BeautifulSoup



def make_soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")
