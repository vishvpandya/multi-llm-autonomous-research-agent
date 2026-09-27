from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from ddgs import DDGS


@dataclass(slots=True)
class SearchHit:
    title: str
    url: str
    snippet: str = ""
    content: str = ""


class SearchProvider(Protocol):
    name: str

    def search(
        self,
        query: str,
        max_results: int = 4,
        preferred_domains: list[str] | None = None,
    ) -> list[SearchHit]: ...


def _normalize_domains(domains: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for value in domains or []:
        candidate = value.strip().lower()
        if not candidate:
            continue
        parsed = urlsplit(candidate if "://" in candidate else f"https://{candidate}")
        hostname = (parsed.hostname or "").removeprefix("www.")
        if hostname and "." in hostname and hostname not in normalized:
            normalized.append(hostname)
    return normalized[:5]


def _domain_constrained_query(query: str, domains: list[str] | None) -> str:
    normalized = _normalize_domains(domains)
    if not normalized or "site:" in query.lower():
        return query
    constraints = " OR ".join(f"site:{domain}" for domain in normalized)
    return f"{query} ({constraints})"


def _is_public_http_url(url: str) -> bool:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return False
    if parts.hostname.lower() in {"localhost", "localhost.localdomain"}:
        return False
    try:
        address = ipaddress.ip_address(parts.hostname)
    except ValueError:
        return True
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
    )


def _extract_page_text(url: str, max_characters: int = 3500) -> str:
    if not _is_public_http_url(url):
        return ""
    try:
        current_url = url
        response = None
        for _ in range(4):
            response = httpx.get(
                current_url,
                follow_redirects=False,
                timeout=8.0,
                headers={"User-Agent": "Mozilla/5.0 AutonomousResearchAgent/1.0"},
            )
            if not response.is_redirect:
                break
            current_url = urljoin(current_url, response.headers.get("location", ""))
            if not _is_public_http_url(current_url):
                return ""
        if response is None or response.is_redirect:
            return ""
        response.raise_for_status()
        if "text/html" not in response.headers.get("content-type", ""):
            return ""
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "form", "noscript"]):
            tag.decompose()
        text = " ".join(soup.get_text(" ", strip=True).split())
        return text[:max_characters]
    except (httpx.HTTPError, ValueError):
        return ""


class DuckDuckGoSearchProvider:
    name = "DuckDuckGo"

    def search(
        self,
        query: str,
        max_results: int = 4,
        preferred_domains: list[str] | None = None,
    ) -> list[SearchHit]:
        effective_query = _domain_constrained_query(query, preferred_domains)
        raw_results = list(DDGS().text(effective_query, max_results=max_results))
        hits: list[SearchHit] = []
        for item in raw_results:
            url = str(item.get("href") or item.get("url") or "")
            if not _is_public_http_url(url):
                continue
            hits.append(
                SearchHit(
                    title=str(item.get("title") or url),
                    url=url,
                    snippet=str(item.get("body") or item.get("snippet") or ""),
                    content=_extract_page_text(url),
                )
            )
        return hits


class TavilySearchProvider:
    name = "Tavily"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("TAVILY_API_KEY is required when using Tavily.")
        self.api_key = api_key

    def search(
        self,
        query: str,
        max_results: int = 4,
        preferred_domains: list[str] | None = None,
    ) -> list[SearchHit]:
        request = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": "advanced",
            "max_results": max_results,
            "include_raw_content": True,
        }
        domains = _normalize_domains(preferred_domains)
        if domains:
            request["include_domains"] = domains
        response = httpx.post(
            "https://api.tavily.com/search",
            json=request,
            timeout=30.0,
        )
        response.raise_for_status()
        hits: list[SearchHit] = []
        for item in response.json().get("results", []):
            url = str(item.get("url") or "")
            if not _is_public_http_url(url):
                continue
            hits.append(
                SearchHit(
                    title=str(item.get("title") or url),
                    url=url,
                    snippet=str(item.get("content") or ""),
                    content=str(item.get("raw_content") or "")[:3500],
                )
            )
        return hits


class SerpApiSearchProvider:
    name = "SerpAPI"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("SERPAPI_API_KEY is required when using SerpAPI.")
        self.api_key = api_key

    def search(
        self,
        query: str,
        max_results: int = 4,
        preferred_domains: list[str] | None = None,
    ) -> list[SearchHit]:
        effective_query = _domain_constrained_query(query, preferred_domains)
        response = httpx.get(
            "https://serpapi.com/search.json",
            params={
                "engine": "google",
                "q": effective_query,
                "api_key": self.api_key,
                "num": max_results,
            },
            timeout=30.0,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise RuntimeError(f"SerpAPI search failed: {payload['error']}")

        hits: list[SearchHit] = []
        for item in payload.get("organic_results", [])[:max_results]:
            url = str(item.get("link") or "")
            if not _is_public_http_url(url):
                continue
            hits.append(
                SearchHit(
                    title=str(item.get("title") or url),
                    url=url,
                    snippet=str(item.get("snippet") or ""),
                    content=_extract_page_text(url),
                )
            )
        return hits


def create_search_provider(
    backend: str = "auto",
    tavily_api_key: str | None = None,
    serpapi_api_key: str | None = None,
) -> SearchProvider:
    tavily_key = tavily_api_key or os.getenv("TAVILY_API_KEY", "")
    serpapi_key = serpapi_api_key or os.getenv("SERPAPI_API_KEY", "")
    normalized = backend.lower()
    if normalized == "auto":
        if tavily_key:
            return TavilySearchProvider(tavily_key)
        if serpapi_key:
            return SerpApiSearchProvider(serpapi_key)
        return DuckDuckGoSearchProvider()
    if normalized == "tavily":
        return TavilySearchProvider(tavily_key)
    if normalized in {"serpapi", "serp_api"}:
        return SerpApiSearchProvider(serpapi_key)
    if normalized in {"duckduckgo", "ddg"}:
        return DuckDuckGoSearchProvider()
    raise ValueError(f"Unknown search backend: {backend}")
