from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import quote, urljoin, urlparse, urlunparse



def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc or parsed.path
    path = parsed.path if parsed.netloc else ""
    if not path:
        path = "/"
    normalized = urlunparse((scheme.lower(), netloc.lower(), path or "/", "", parsed.query, ""))
    return normalized



def site_root(url: str) -> str:
    parsed = urlparse(normalize_url(url))
    return urlunparse((parsed.scheme, parsed.netloc, "/", "", "", ""))



def path_prefixes(url: str) -> list[str]:
    parsed = urlparse(normalize_url(url))
    path = PurePosixPath(parsed.path)
    prefixes: list[str] = []
    if parsed.path == "/":
        return [site_root(url)]
    parts = [part for part in path.parts if part != "/"]
    if parts and "." in parts[-1]:
        parts = parts[:-1]
    current = site_root(url).rstrip("/")
    prefixes.append(current + "/")
    accum = ""
    for part in parts:
        accum += "/" + part
        prefixes.append(current + accum)
    unique = []
    seen = set()
    for item in prefixes:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique



def llms_probe_urls(url: str) -> list[str]:
    probes: list[str] = []
    roots = path_prefixes(url)
    for root in roots:
        root = root.rstrip("/")
        probes.append(root + "/llms.txt")
        probes.append(root + "/llms-full.txt")
    seen = set()
    ordered: list[str] = []
    for item in probes:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered



def absolutize(base_url: str, maybe_relative: str) -> str:
    return urljoin(base_url, maybe_relative)



def markdown_twin_urls(url: str) -> list[str]:
    normalized = normalize_url(url)
    parsed = urlparse(normalized)
    path = parsed.path or "/"
    candidates: list[str] = []
    if path.endswith(".md"):
        return [normalized]
    if path.endswith("/"):
        candidates.append(urljoin(normalized, "index.md"))
        candidates.append(normalized.rstrip("/") + ".md")
    else:
        candidates.append(normalized + ".md")
        candidates.append(normalized.rstrip("/") + "/index.md")
    candidates.append(normalized.rstrip("/") + ".markdown")
    candidates.append(normalized.rstrip("/") + "/index.markdown")
    seen = set()
    ordered: list[str] = []
    for item in candidates:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered



def same_host(url_a: str, url_b: str) -> bool:
    return urlparse(normalize_url(url_a)).netloc == urlparse(normalize_url(url_b)).netloc



def same_section(root_url: str, candidate_url: str) -> bool:
    a = urlparse(normalize_url(root_url))
    b = urlparse(normalize_url(candidate_url))
    if a.netloc != b.netloc:
        return False
    prefix = a.path.rstrip("/")
    if not prefix:
        return True
    return b.path == prefix or b.path.startswith(prefix + "/")



def safe_filename_from_url(url: str) -> str:
    parsed = urlparse(normalize_url(url))
    path = parsed.path.strip("/") or "index"
    path = path.replace("/", "__")
    if parsed.query:
        path += "__" + quote(parsed.query, safe="")
    return path
