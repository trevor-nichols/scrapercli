from __future__ import annotations

import re
from typing import Iterable


WHITESPACE_RE = re.compile(r"\s+")
SENTENCE_RE = re.compile(r"[.!?][\"')\]]?\s")
BYLINE_RE = re.compile(r"\b(by|author|written by|updated|published)\b", re.I)
BOILERPLATE_KEYWORDS = {
    "privacy",
    "terms",
    "cookies",
    "cookie",
    "share",
    "subscribe",
    "sign in",
    "login",
    "related",
    "newsletter",
    "menu",
}



def normalize_whitespace(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text).strip()



def normalize_line_whitespace(text: str) -> str:
    lines = [WHITESPACE_RE.sub(" ", line).rstrip() for line in text.splitlines()]
    return "\n".join(line for line in lines).strip()



def sentence_like(text: str) -> bool:
    return bool(SENTENCE_RE.search(text))



def paragraph_count_from_text(text: str) -> int:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return len(paragraphs)



def heading_count_from_markdown(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.startswith("#"))



def code_fence_count(text: str) -> int:
    return text.count("```") // 2



def table_count_from_markdown(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip().startswith("|"))



def link_density(text_chars: int, linked_text_chars: int) -> float:
    if text_chars <= 0:
        return 0.0
    return max(0.0, min(1.0, linked_text_chars / max(1, text_chars)))



def keyword_hits(text: str, vocabulary: Iterable[str] | None = None) -> list[str]:
    haystack = normalize_whitespace(text).lower()
    vocab = set(vocabulary or BOILERPLATE_KEYWORDS)
    return sorted([keyword for keyword in vocab if keyword in haystack])



def looks_like_byline(text: str) -> bool:
    compact = normalize_whitespace(text)
    return 20 <= len(compact) <= 250 and bool(BYLINE_RE.search(compact))



def slugify(text: str, max_length: int = 80) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return slug[:max_length] or "document"



def first_meaningful_line(text: str) -> str | None:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return None
