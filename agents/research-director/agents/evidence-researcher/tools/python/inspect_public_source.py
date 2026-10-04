"""Fetch one public source through a named, auditable inspection boundary."""

from __future__ import annotations

import hashlib
import ipaddress
import socket
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from omnigent_client.tools import tool

_USER_AGENT = "Ai-Researcher/1.0 (+https://github.com/buh07/Ai-Researcher)"
_MAX_RESPONSE_BYTES = 2_000_000


def _assert_public_http_url(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("url must be a non-empty string")
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("url must identify a public HTTP or HTTPS source")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("url must not contain credentials")
    try:
        addresses = {
            ipaddress.ip_address(item[4][0])
            for item in socket.getaddrinfo(
                parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        }
    except (OSError, ValueError) as exc:
        raise ValueError(f"url host could not be resolved: {parsed.hostname}") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("url must resolve only to public network addresses")
    return value


class _ReadableHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self._title_depth = 0
        self._ignored_depth = 0

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        del attrs
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1
        if tag == "title":
            self._title_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._title_depth:
            self._title_depth -= 1
        if tag in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._title_depth:
            self.title_parts.append(data)
        self.text_parts.append(data)


class _PublicRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request | None:
        _assert_public_http_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_public_source(request: Request, timeout_seconds: float) -> Any:
    return build_opener(_PublicRedirectHandler()).open(
        request, timeout=timeout_seconds
    )


def _clean_text(parts: list[str]) -> str:
    return " ".join(" ".join(parts).split())


def _inspect(url: str, timeout_seconds: float, max_chars: int) -> dict[str, Any]:
    requested_url = _assert_public_http_url(url)
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise ValueError("timeout_seconds must be numeric")
    if not 1 <= float(timeout_seconds) <= 30:
        raise ValueError("timeout_seconds must be between 1 and 30")
    if isinstance(max_chars, bool) or not isinstance(max_chars, int):
        raise ValueError("max_chars must be an integer")
    if not 500 <= max_chars <= 50_000:
        raise ValueError("max_chars must be between 500 and 50000")

    request = Request(
        requested_url,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/json,application/xml,text/plain;q=0.9,*/*;q=0.1",
        },
    )
    try:
        with _open_public_source(request, float(timeout_seconds)) as response:
            body = response.read(_MAX_RESPONSE_BYTES + 1)
            final_url = response.geturl()
            status = int(getattr(response, "status", 200))
            content_type = response.headers.get_content_type().lower()
            charset = response.headers.get_content_charset() or "utf-8"
    except Exception as exc:
        raise RuntimeError(f"public source inspection failed: {exc}") from exc
    if len(body) > _MAX_RESPONSE_BYTES:
        raise RuntimeError("public source response exceeded the size limit")
    _assert_public_http_url(final_url)
    if status < 200 or status >= 300:
        raise RuntimeError(f"public source returned HTTP status {status}")
    if not (
        content_type.startswith("text/")
        or content_type in {"application/json", "application/xml", "application/xhtml+xml"}
        or content_type.endswith("+json")
        or content_type.endswith("+xml")
    ):
        raise RuntimeError(f"public source content type is not inspectable text: {content_type}")

    decoded = body.decode(charset, errors="replace")
    title = ""
    if content_type in {"text/html", "application/xhtml+xml"}:
        parser = _ReadableHTML()
        parser.feed(decoded)
        title = _clean_text(parser.title_parts)
        text = _clean_text(parser.text_parts)
    else:
        text = _clean_text([decoded])
    if not text:
        raise RuntimeError("public source contained no inspectable text")
    excerpt = text[:max_chars]
    return {
        "schema": "public-source-inspection/v1",
        "requested_url": requested_url,
        "final_url": final_url,
        "http_status": status,
        "content_type": content_type,
        "retrieved_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "title": title,
        "text_excerpt": excerpt,
        "truncated": len(text) > len(excerpt),
    }


@tool
def inspect_public_source(
    url: str, timeout_seconds: float = 20.0, max_chars: int = 12_000
) -> dict[str, Any]:
    """Retrieve and normalize one explicit public source for direct inspection.

    Args:
        url: Exact public HTTP or HTTPS source URL to inspect.
        timeout_seconds: Network timeout from 1 through 30 seconds.
        max_chars: Maximum normalized source characters to return, 500 through 50000.
    """

    return _inspect(url, timeout_seconds, max_chars)
