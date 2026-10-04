"""Credential-free public-web search for evidence discovery.

Omnigent 0.16 exposes its built-in search as an unnamed
``web_search_preview`` schema to the Codex adapter, which the adapter drops.
This named local tool preserves an auditable live-search call boundary by
querying DuckDuckGo Lite over HTTPS and returning discovery metadata. Search
snippets are discovery aids, not citable support; agents must inspect the
underlying sources before recording a verified claim.
"""

from __future__ import annotations

from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse
from urllib.request import Request, urlopen

from omnigent_client.tools import tool

_SEARCH_ENDPOINT = "https://lite.duckduckgo.com/lite/?q="
_USER_AGENT = "Ai-Researcher/1.0 (+https://github.com/buh07/Ai-Researcher)"
_MAX_RESPONSE_BYTES = 2_000_000


def _result_url(href: str) -> str:
    absolute = urljoin("https://duckduckgo.com", href)
    parsed = urlparse(absolute)
    redirected = parse_qs(parsed.query).get("uddg", [])
    return redirected[0] if redirected else absolute


class _ResultsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._capture: str | None = None
        self._buffer: list[str] = []
        self._pending_href: str | None = None

    @staticmethod
    def _classes(attrs: list[tuple[str, str | None]]) -> set[str]:
        value = next((value for key, value in attrs if key == "class"), "") or ""
        return set(value.split())

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        classes = self._classes(attrs)
        if tag == "a" and "result-link" in classes:
            self._capture = "title"
            self._buffer = []
            self._pending_href = next(
                (value for key, value in attrs if key == "href" and value), None
            )
        elif tag == "td" and "result-snippet" in classes and self.results:
            self._capture = "snippet"
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._capture is not None:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._capture == "title":
            title = " ".join("".join(self._buffer).split())
            if title and self._pending_href:
                self.results.append(
                    {
                        "title": title,
                        "url": _result_url(self._pending_href),
                        "snippet": "",
                    }
                )
            self._capture = None
            self._buffer = []
            self._pending_href = None
        elif tag == "td" and self._capture == "snippet":
            self.results[-1]["snippet"] = " ".join("".join(self._buffer).split())
            self._capture = None
            self._buffer = []


def _search(query: str, max_results: int, timeout_seconds: float) -> dict[str, Any]:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    query = query.strip()
    if len(query) > 500:
        raise ValueError("query must not exceed 500 characters")
    if isinstance(max_results, bool) or not isinstance(max_results, int):
        raise ValueError("max_results must be an integer")
    if not 1 <= max_results <= 10:
        raise ValueError("max_results must be between 1 and 10")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise ValueError("timeout_seconds must be numeric")
    if not 1 <= float(timeout_seconds) <= 30:
        raise ValueError("timeout_seconds must be between 1 and 30")

    retrieved_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    request = Request(
        _SEARCH_ENDPOINT + quote_plus(query),
        headers={"User-Agent": _USER_AGENT, "Accept": "text/html"},
    )
    try:
        with urlopen(request, timeout=float(timeout_seconds)) as response:
            body = response.read(_MAX_RESPONSE_BYTES + 1)
            final_url = response.geturl()
    except Exception as exc:
        raise RuntimeError(f"public web search failed: {exc}") from exc
    if len(body) > _MAX_RESPONSE_BYTES:
        raise RuntimeError("public web search response exceeded the size limit")

    decoded = body.decode("utf-8", errors="replace")
    parser = _ResultsParser()
    parser.feed(decoded)
    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for result in parser.results:
        if result["url"] in seen:
            continue
        seen.add(result["url"])
        unique.append(result)
        if len(unique) == max_results:
            break
    if not unique:
        lowered = decoded.lower()
        if any(
            marker in lowered
            for marker in ("challenge", "automated traffic", "anomaly")
        ):
            raise RuntimeError(
                "public web search was rate-limited by an automated-traffic challenge; "
                "do not retry it in a loop—inspect explicit credible source URLs with "
                "inspect_public_source instead"
            )
        raise RuntimeError("public web search returned no parseable results")
    return {
        "schema": "public-web-search-result/v1",
        "query": query,
        "engine": "DuckDuckGo Lite",
        "request_url": final_url,
        "retrieved_at": retrieved_at,
        "results": unique,
        "usage_note": (
            "Search snippets are discovery aids only; inspect the underlying "
            "source before recording a verified external claim."
        ),
    }


@tool
def search_public_web(
    query: str, max_results: int = 5, timeout_seconds: float = 20.0
) -> dict[str, Any]:
    """Search the live public web through a named, auditable HTTPS boundary.

    Args:
        query: Focused search query. Use source/domain qualifiers when useful.
        max_results: Number of unique results to return, from 1 through 10.
        timeout_seconds: Network timeout from 1 through 30 seconds.
    """

    return _search(query, max_results, timeout_seconds)
