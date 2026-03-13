from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from ..models import FetchSnapshot, ScraperConfig
from ..observability.recorder import DecisionRecorder
from ..observability.store import ArtifactStore
from ..utils.url import normalize_url
from .cache import ConditionalRequestCache


class HttpFetchError(RuntimeError):
    pass


@dataclass
class _RateLimiter:
    requests_per_second: float
    last_seen: dict[str, float] = field(default_factory=dict)

    def wait(self, url: str) -> None:
        if self.requests_per_second <= 0:
            return
        host = urlparse(url).netloc
        min_interval = 1.0 / self.requests_per_second
        now = time.monotonic()
        last = self.last_seen.get(host)
        if last is not None:
            elapsed = now - last
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
        self.last_seen[host] = time.monotonic()


class HttpClient:
    def __init__(self, config: ScraperConfig, artifacts: ArtifactStore, recorder: DecisionRecorder) -> None:
        self.config = config
        self.artifacts = artifacts
        self.recorder = recorder
        timeout = httpx.Timeout(config.timeout_seconds)
        client_kwargs: dict[str, Any] = {
            "timeout": timeout,
            "headers": {"User-Agent": config.user_agent, **config.default_headers},
            "follow_redirects": True,
            "http2": True,
        }
        if config.proxies:
            if len(config.proxies) == 1:
                client_kwargs["proxy"] = next(iter(config.proxies.values()))
            else:
                client_kwargs["mounts"] = {scheme: httpx.HTTPTransport(proxy=proxy_url) for scheme, proxy_url in config.proxies.items()}
        self.client = httpx.Client(**client_kwargs)
        for name, value in config.cookies.items():
            self.client.cookies.set(name, value)
        self.rate_limiter = _RateLimiter(config.rate_limit.requests_per_second)
        self.conditional_cache = ConditionalRequestCache(artifacts.conditional_cache_path)

    def close(self) -> None:
        self.client.close()

    def fetch(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        json_payload: Any | None = None,
        content: str | bytes | None = None,
        conditional: bool = False,
        allow_status: set[int] | None = None,
    ) -> FetchSnapshot:
        normalized = normalize_url(url)
        allow_status = allow_status or set()
        merged_headers = dict(headers or {})
        if conditional and method.upper() in {"GET", "HEAD"}:
            merged_headers.update(self.conditional_cache.get_headers(normalized))
        attempt = 0
        start = time.perf_counter()
        while attempt < self.config.retry.attempts:
            attempt += 1
            self.rate_limiter.wait(normalized)
            try:
                response = self.client.request(
                    method.upper(),
                    normalized,
                    headers=merged_headers,
                    json=json_payload,
                    content=content,
                )
                if response.status_code in self.config.retry.retryable_status_codes and attempt < self.config.retry.attempts:
                    self.recorder.record(
                        "http",
                        normalized,
                        "retryable_status",
                        {"status_code": response.status_code, "attempt": attempt},
                    )
                    time.sleep(self.config.retry.backoff_seconds * (self.config.retry.backoff_multiplier ** (attempt - 1)))
                    continue
                break
            except httpx.HTTPError as exc:
                self.recorder.record(
                    "http",
                    normalized,
                    "transport_error",
                    {"attempt": attempt, "error": str(exc)},
                    level="warning",
                )
                if attempt < self.config.retry.attempts:
                    time.sleep(self.config.retry.backoff_seconds * (self.config.retry.backoff_multiplier ** (attempt - 1)))
                    continue
                raise HttpFetchError(f"Failed to fetch {normalized}: {exc}") from exc
        else:
            raise HttpFetchError(f"Failed to fetch {normalized}")

        body = response.content
        artifact_path, body_hash = self.artifacts.save_response(normalized, method.upper(), body, dict(response.headers), response.status_code)
        content_type = response.headers.get("content-type")
        text: str | None = None
        if body:
            try:
                text = response.text
            except UnicodeDecodeError:
                text = None
        snapshot = FetchSnapshot(
            url=normalized,
            final_url=str(response.url),
            method=method.upper(),
            status_code=response.status_code,
            headers={str(k): str(v) for k, v in response.headers.items()},
            content_type=content_type,
            text=text,
            body_sha256=body_hash,
            artifact_path=artifact_path,
            is_not_modified=response.status_code == 304,
            etag=response.headers.get("etag"),
            last_modified=response.headers.get("last-modified"),
        )
        if response.status_code not in {200, 201, 202, 203, 204, 206, 304, *allow_status}:
            self.recorder.record(
                "http",
                normalized,
                "unexpected_status",
                {"status_code": response.status_code, "elapsed_ms": int((time.perf_counter() - start) * 1000)},
                level="warning",
            )
        else:
            self.recorder.record(
                "http",
                normalized,
                "fetched",
                {
                    "status_code": response.status_code,
                    "content_type": content_type,
                    "elapsed_ms": int((time.perf_counter() - start) * 1000),
                    "conditional": conditional,
                },
            )
        if response.status_code != 304:
            self.conditional_cache.update(normalized, etag=snapshot.etag, last_modified=snapshot.last_modified)
        return snapshot
