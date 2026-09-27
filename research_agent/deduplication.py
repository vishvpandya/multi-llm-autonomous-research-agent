from __future__ import annotations

from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import Source


TRACKING_PARAMETERS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "source",
}


def canonicalize_url(url: str) -> str:
    """Normalize a URL so tracking variants collapse to one source."""
    try:
        parts = urlsplit(url.strip())
        query = [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMETERS
        ]
        path = parts.path.rstrip("/") or "/"
        return urlunsplit(
            (parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), "")
        )
    except ValueError:
        return url.strip()


def deduplicate_sources(sources: list[Source]) -> list[Source]:
    unique: list[Source] = []
    seen_urls: set[str] = set()

    for source in sources:
        if not source.url:
            continue
        normalized_url = canonicalize_url(source.url)
        normalized_title = " ".join(source.title.lower().split())
        if normalized_url in seen_urls:
            continue
        if normalized_title and any(
            SequenceMatcher(None, normalized_title, " ".join(item.title.lower().split())).ratio()
            >= 0.94
            for item in unique
        ):
            continue
        seen_urls.add(normalized_url)
        unique.append(Source(source.title or source.url, normalized_url, source.search_query))

    return unique

