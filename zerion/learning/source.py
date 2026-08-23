"""Small, Android-safe topic source adapter.

Uses only requests (already a core dependency) and a public encyclopedia
summary endpoint. It is deliberately bounded and read-only: a fetch is source
material, not proof, and no browser or desktop dependency is required.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

import requests


_MAX_TEXT = 16000
_TIMEOUT = 12


@dataclass(frozen=True)
class SourceMaterial:
    text: str
    url: str
    title: str


def fetch_url(url: str) -> SourceMaterial | None:
    """Fetch an explicitly supplied public HTTP(S) source, bounded and
    read-only. Local/private hostnames are rejected before any request."""
    from urllib.parse import urlparse

    url = (url or "").strip()
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in ("http", "https") or not host:
            return None
        if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"} or host.endswith(".local"):
            return None
        response = requests.get(
            url, headers={"User-Agent": "Zerion/1.0"},
            timeout=_TIMEOUT,
        )
        if response.status_code != 200:
            return None
        text = response.text[:_MAX_TEXT].strip()
        if not text:
            return None
        return SourceMaterial(text=text, url=url[:1000], title=url[:200])
    except Exception:
        return None


def fetch_topic(topic: str) -> SourceMaterial | None:
    """Fetch a public Wikipedia summary for a topic, if network is usable.

    This is a convenience source for Termux/Android. It never claims that the
    result is complete or verified; callers must preserve that provenance.
    """
    topic = " ".join((topic or "").split())
    if not topic or len(topic) > 160:
        return None
    url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + quote(
        topic.replace(" ", "_"), safe="")
    try:
        response = requests.get(
            url,
            headers={"Accept": "application/json", "User-Agent": "Zerion/1.0"},
            timeout=_TIMEOUT,
        )
        if response.status_code != 200:
            return None
        data = response.json()
        extract = str(data.get("extract", "")).strip()[:_MAX_TEXT]
        title = str(data.get("title", topic)).strip()[:200]
        if not extract:
            return None
        return SourceMaterial(text=extract, url=url, title=title)
    except Exception:
        # Network/source failure is a normal degraded state, not a reason to
        # crash the learning or conversation path.
        return None
