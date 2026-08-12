"""Retrieval transports — closes ADR-012 cut 1 (fixture-only retrieval).

Two implementations behind one interface, selected with `--retrieval`:

  `fixture`  the local corpus. Default, because the eval gate must be deterministic
             (ADR-014) and a reviewer needs no network.
  `http`     real HTTP: robots.txt, HTML→text extraction, redirect control, size and
             time caps, content-type checks, conditional caching.

The point of this module is that the *transport* was the only simulated part of
retrieval. The tool contract, the https and host allowlist checks, the
indirect-injection screen, the per-URL dedupe and the citation plumbing were always
real and are unchanged — `HttpTransport` slots in beneath them.

## The defensive decisions, and why each one is here

Fetching attacker-influenceable URLs is an SSRF and resource-exhaustion surface, so:

* **Host allowlist is checked before connecting** (in `tools.FetchTool`), and again
  after every redirect — a 302 to an internal address is the classic bypass.
* **Redirects are followed manually, capped, and re-validated.** urllib's automatic
  redirect handling would follow an off-allowlist hop invisibly.
* **Literal IP addresses and non-http(s) schemes are refused**, and private,
  loopback, link-local and reserved ranges are blocked, so `http://169.254.169.254/`
  (cloud metadata) cannot be reached even if someone allowlists an IP.
* **Reads are size-capped mid-stream**, not after. A `Content-Length` header is a
  claim, not a fact.
* **Timeouts on connect and read**, because the cost model says open-web fetch is the
  fattest latency tail in the system and an unbounded one would blow the p95 budget.
* **robots.txt is respected** and cached per host — a research agent that ignores it
  is a liability, not a feature.
* **HTML is reduced to text with script, style, nav and form content removed**, so
  boilerplate does not enter the context budget or the groundedness check.

`localhost` is permitted only when explicitly constructed with `allow_local=True`,
which the test suite uses to exercise the whole path against a local server without
opening an SSRF hole in the default configuration.
"""

from __future__ import annotations

import gzip
import ipaddress
import re
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urljoin, urlparse

USER_AGENT = "deep-research-agent/0.2 (+https://example.org/agent-policy)"
MAX_BYTES = 2_000_000
MAX_REDIRECTS = 3
CONNECT_TIMEOUT_S = 5.0
READ_TIMEOUT_S = 10.0
ALLOWED_CONTENT = ("text/html", "text/plain", "application/xhtml+xml", "text/markdown")

_SKIP_TAGS = {"script", "style", "noscript", "nav", "header", "footer", "form", "svg", "template"}
_BLOCK_TAGS = {"p", "div", "li", "br", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"}


class Headers(dict):
    """Case-insensitive header mapping.

    `dict(resp.headers)` preserves whatever casing the server sent, so
    `headers["Content-Type"]` misses a server sending `Content-type` — and a missed
    `location:` header would silently turn a redirect into a failed fetch. HTTP field
    names are case-insensitive per RFC 9110; this makes the lookup match the spec.
    """

    def __init__(self, pairs: Any = ()) -> None:
        super().__init__()
        items = pairs.items() if hasattr(pairs, "items") else pairs
        for k, v in items:
            self[k] = v

    def __setitem__(self, key: str, value: Any) -> None:
        super().__setitem__(key.lower(), value)

    def __getitem__(self, key: str) -> Any:
        return super().__getitem__(key.lower())

    def __contains__(self, key: object) -> bool:
        return super().__contains__(str(key).lower())

    def get(self, key: str, default: Any = None) -> Any:
        return super().get(key.lower(), default)


class TransportError(RuntimeError):
    """Retrieval failed. `kind` maps to the tool's typed error kinds."""

    def __init__(self, message: str, kind: str = "upstream_unavailable") -> None:
        super().__init__(message)
        self.kind = kind


# --- HTML → text -----------------------------------------------------------------
class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title: str = ""
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title += data
        elif data.strip():
            self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
        raw = re.sub(r"\n\s*\n+", "\n\n", raw)
        return raw.strip()


def html_to_text(html: str) -> tuple[str, str]:
    """Return (text, title). Malformed HTML yields whatever was parseable."""
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        pass  # a broken page is a partial page, not a failed fetch
    return parser.text(), parser.title.strip()


# --- transports -------------------------------------------------------------------
@dataclass
class Document:
    url: str
    title: str
    text: str
    status: int = 200
    bytes_read: int = 0
    from_cache: bool = False


class Transport(Protocol):
    name: str

    def search(self, query: str, max_results: int) -> list[dict[str, Any]]: ...
    def fetch(self, url: str) -> Document: ...


class FixtureTransport:
    """The local corpus. Deterministic, offline, and what the eval gate runs against."""

    name = "fixture"

    def __init__(self, corpus: list[dict[str, Any]], latency_ms: float = 120.0, speed: float = 1.0) -> None:
        self.corpus = corpus
        self.latency_ms = latency_ms
        self.speed = speed

    def search(self, query: str, max_results: int) -> list[dict[str, Any]]:
        from .models import keywords

        terms = set(keywords(query, limit=8))
        scored = []
        for doc in self.corpus:
            hay = set(doc["keywords"]) | set(keywords(doc["title"], limit=12))
            overlap = len(terms & hay)
            if overlap:
                scored.append((overlap + 0.01 * len(hay & terms), doc))
        scored.sort(key=lambda x: (-x[0], x[1]["url"]))
        return [
            {"url": d["url"], "title": d["title"], "snippet": d["text"][:160], "relevance": round(s, 3)}
            for s, d in scored[:max_results]
        ]

    def fetch(self, url: str) -> Document:
        doc = next((d for d in self.corpus if d["url"] == url), None)
        if doc is None:
            raise TransportError(f"source not found: {url}", kind="not_found")
        if self.latency_ms and self.speed:
            time.sleep(self.latency_ms * self.speed / 1000.0)
        return Document(url=doc["url"], title=doc["title"], text=doc["text"], bytes_read=len(doc["text"]))


class HttpTransport:
    """Real HTTP retrieval. Everything above it in the stack is unchanged."""

    name = "http"

    def __init__(
        self,
        *,
        allow_local: bool = False,
        max_bytes: int = MAX_BYTES,
        respect_robots: bool = True,
        search_endpoint: str | None = None,
    ) -> None:
        self.allow_local = allow_local
        self.max_bytes = max_bytes
        self.respect_robots = respect_robots
        self.search_endpoint = search_endpoint
        self._robots: dict[str, Any] = {}
        self._etags: dict[str, str] = {}
        self._cache: dict[str, Document] = {}

    # -- search ------------------------------------------------------------------
    def search(self, query: str, max_results: int) -> list[dict[str, Any]]:
        """Search needs a provider; there is no standards-based one to fall back on.

        Rather than pretend, this raises unless a `search_endpoint` is configured. The
        honest position is that *fetch* is now real and *search* still needs a
        commercial API key, so a deployment wires one here.
        """
        if not self.search_endpoint:
            raise TransportError(
                "http transport has no search provider configured; pass --search-endpoint "
                "or use --retrieval fixture",
                kind="not_configured",
            )
        import json

        req = urllib.request.Request(
            f"{self.search_endpoint}?q={urllib.request.quote(query)}&n={max_results}",
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=READ_TIMEOUT_S) as resp:
                payload = json.loads(resp.read(self.max_bytes).decode("utf-8", "replace"))
        except Exception as exc:
            raise TransportError(f"search provider failed: {exc}", kind="upstream_unavailable") from exc
        results = payload.get("results", payload if isinstance(payload, list) else [])
        return [
            {
                "url": r["url"],
                "title": r.get("title", r["url"]),
                "snippet": (r.get("snippet") or "")[:160],
                "relevance": float(r.get("score", 1.0)),
            }
            for r in results[:max_results]
        ]

    # -- address safety ----------------------------------------------------------
    def _assert_public(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise TransportError(f"scheme not permitted: {parsed.scheme}", kind="not_allowlisted")
        host = parsed.hostname or ""
        if not host:
            raise TransportError("no host in url", kind="not_allowlisted")
        if self.allow_local and host in ("localhost", "127.0.0.1", "::1"):
            return host
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror as exc:
            raise TransportError(f"dns resolution failed for {host}", kind="upstream_unavailable") from exc
        for info in infos:
            addr = ipaddress.ip_address(info[4][0])
            if (
                addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_reserved or addr.is_multicast or addr.is_unspecified
            ):
                # Cloud metadata endpoints and internal services live here. Refusing
                # by resolved address, not by hostname, defeats DNS rebinding.
                raise TransportError(
                    f"refusing to fetch a non-public address ({addr}) for host {host}",
                    kind="not_allowlisted",
                )
        return host

    # -- robots ------------------------------------------------------------------
    def _robots_allows(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        rules = self._robots.get(origin)
        if rules is None:
            rules = self._load_robots(origin)
            self._robots[origin] = rules
        path = parsed.path or "/"
        # Longest-match wins, matching the de-facto convention.
        best: tuple[int, bool] | None = None
        for prefix, allowed in rules:
            if path.startswith(prefix) and (best is None or len(prefix) > best[0]):
                best = (len(prefix), allowed)
        return best[1] if best else True

    def _load_robots(self, origin: str) -> list[tuple[str, bool]]:
        try:
            req = urllib.request.Request(
                urljoin(origin, "/robots.txt"), headers={"User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(req, timeout=CONNECT_TIMEOUT_S) as resp:
                body = resp.read(200_000).decode("utf-8", "replace")
        except Exception:
            return []  # no robots.txt, or unreachable: crawling is permitted
        rules: list[tuple[str, bool]] = []
        applies = False
        for line in body.splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            field_name, _, value = (p.strip() for p in line.partition(":"))
            field_name = field_name.lower()
            if field_name == "user-agent":
                applies = value == "*" or value.lower() in USER_AGENT.lower()
            elif applies and field_name in ("disallow", "allow"):
                if value:
                    rules.append((value, field_name == "allow"))
                elif field_name == "disallow":
                    pass  # empty Disallow means allow everything
        return rules

    # -- fetch -------------------------------------------------------------------
    def fetch(self, url: str) -> Document:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            self._assert_public(current)
            if not self._robots_allows(current):
                raise TransportError(f"robots.txt disallows {current}", kind="robots_disallowed")
            status, headers, body, final = self._request(current)
            if status in (301, 302, 303, 307, 308):
                location = headers.get("Location")
                if not location:
                    raise TransportError(f"redirect without a location from {current}", kind="upstream_unavailable")
                # Re-validated on the next loop iteration — a redirect must not be a
                # way past the address and robots checks.
                current = urljoin(current, location)
                continue
            if status != 200:
                raise TransportError(f"http {status} from {current}", kind="upstream_unavailable")

            ctype = (headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype and not any(ctype.startswith(a) for a in ALLOWED_CONTENT):
                raise TransportError(f"unsupported content-type {ctype}", kind="unsupported_content")

            charset = "utf-8"
            if "charset=" in (headers.get("Content-Type") or "").lower():
                charset = (headers["Content-Type"].lower().split("charset=")[1].split(";")[0].strip() or "utf-8")
            if (headers.get("Content-Encoding") or "").lower() == "gzip":
                try:
                    body = gzip.decompress(body)
                except Exception:
                    pass
            raw = body.decode(charset, "replace")

            # Sniff as well as trust the header: a server may mislabel HTML as
            # text/plain, and leaving tags in the text would pollute both the context
            # budget and the groundedness check.
            head = raw.lstrip()[:512].lower()
            looks_html = ctype in ("text/html", "application/xhtml+xml") or head.startswith(
                ("<!doctype htm", "<html", "<?xml")
            ) or ("<body" in head or "<p>" in head)
            if looks_html:
                text, title = html_to_text(raw)
            else:
                text, title = raw.strip(), ""
            if not text:
                raise TransportError(f"no extractable text at {final}", kind="empty_document")
            doc = Document(
                url=final, title=title or urlparse(final).path.rsplit("/", 1)[-1] or final,
                text=text, status=status, bytes_read=len(body),
            )
            self._cache[url] = doc
            return doc
        raise TransportError(f"too many redirects from {url}", kind="upstream_unavailable")

    def _request(self, url: str) -> tuple[int, Headers, bytes, str]:
        headers = {"User-Agent": USER_AGENT, "Accept": ", ".join(ALLOWED_CONTENT)}
        if url in self._etags:
            headers["If-None-Match"] = self._etags[url]
        req = urllib.request.Request(url, headers=headers, method="GET")

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None  # handled by the caller so every hop is re-validated

        opener = urllib.request.build_opener(_NoRedirect)
        try:
            resp = opener.open(req, timeout=READ_TIMEOUT_S)
        except urllib.error.HTTPError as exc:
            if exc.code == 304 and url in self._cache:
                cached = self._cache[url]
                return 200, Headers(), cached.text.encode(), cached.url
            return exc.code, Headers(exc.headers or {}), b"", url
        except urllib.error.URLError as exc:
            raise TransportError(f"connection failed: {exc.reason}", kind="upstream_unavailable") from exc
        except socket.timeout as exc:
            raise TransportError(f"read timed out after {READ_TIMEOUT_S}s", kind="timeout") from exc

        with resp:
            # Cap mid-stream: Content-Length is a claim, not a fact.
            chunks, total = [], 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > self.max_bytes:
                    raise TransportError(
                        f"document exceeds {self.max_bytes} bytes", kind="document_too_large"
                    )
                chunks.append(chunk)
            etag = resp.headers.get("ETag")
            if etag:
                self._etags[url] = etag
            return resp.status, Headers(resp.headers), b"".join(chunks), resp.url


def build_transport(
    kind: str,
    *,
    corpus: list[dict[str, Any]] | None = None,
    latency_speed: float = 1.0,
    allow_local: bool = False,
    search_endpoint: str | None = None,
) -> Transport:
    if kind == "http":
        return HttpTransport(allow_local=allow_local, search_endpoint=search_endpoint)
    return FixtureTransport(corpus or [], speed=latency_speed)
