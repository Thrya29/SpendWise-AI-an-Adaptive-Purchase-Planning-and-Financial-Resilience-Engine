"""Fetch a public product page safely.

Defences against server-side request forgery (SSRF) and abuse:
* http/https only, default ports only, no credentials in URLs;
* every address the host resolves to must be public (no loopback, private,
  link-local incl. cloud metadata 169.254.169.254, multicast, reserved);
* redirects are followed manually (max 3) and every hop is re-validated;
* size cap, timeout, HTML content types only;
* robots.txt is honoured for our user agent.

Residual risk (documented): a hostile DNS server could answer differently between
our check and the connection (DNS rebinding). The blast radius is limited because
the API container cannot reach anything sensitive except its own database and
cache, which are also blocked by name/address checks.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

USER_AGENT = "SpendWiseBot/1.0 (+personal price check; respects robots.txt)"
MAX_BYTES = 2_000_000
TIMEOUT_S = 15.0
MAX_REDIRECTS = 3
_ALLOWED_PORTS = {None, 80, 443}
_HTML_TYPES = ("text/html", "application/xhtml+xml")

Resolver = Callable[[str], Awaitable[list[str]]]


class FetchError(Exception):
    """A page could not be fetched; ``reason`` is safe to show to users."""

    def __init__(self, reason: str, *, code: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.code = code


@dataclass(frozen=True, slots=True)
class Page:
    url: str  # final URL after redirects
    status: int
    html: str


async def system_resolver(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
        or ip.is_reserved or ip.is_unspecified
    )  # fmt: skip


async def validate_url(url: str, resolver: Resolver) -> str:
    """Return the normalised URL or raise ``FetchError``."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError as exc:
        raise FetchError("That link is not a valid web address.", code="invalid_url") from exc
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise FetchError("Only http and https links are supported.", code="invalid_url")
    if parts.username or parts.password:
        raise FetchError("Links with embedded credentials are not allowed.", code="invalid_url")
    if port not in _ALLOWED_PORTS:
        raise FetchError("Links on non-standard ports are not allowed.", code="blocked")
    host = parts.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise FetchError("That address is not a public website.", code="blocked")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        addresses = [str(literal)]
    else:
        try:
            addresses = await resolver(host)
        except (OSError, UnicodeError) as exc:
            raise FetchError("That website could not be found.", code="dns") from exc
    if not addresses or not all(_is_public(a) for a in addresses):
        raise FetchError("That address is not a public website.", code="blocked")
    return parts.geturl()


class SafeFetcher:
    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        resolver: Resolver = system_resolver,
        *,
        check_robots: bool = True,
    ) -> None:
        self._client = client or httpx.AsyncClient(
            timeout=TIMEOUT_S,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        )
        self._resolver = resolver
        self._check_robots = check_robots

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, url: str, max_bytes: int) -> tuple[httpx.Response, bytes]:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            current = await validate_url(current, self._resolver)
            try:
                async with self._client.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise FetchError("The website sent a broken redirect.", code="http")
                        current = urljoin(current, location)
                        continue
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            raise FetchError("That page is too large to read.", code="too_large")
                    return response, bytes(body)
            except httpx.TimeoutException as exc:
                raise FetchError("The website took too long to respond.", code="timeout") from exc
            except httpx.HTTPError as exc:
                raise FetchError("Could not connect to that website.", code="network") from exc
        raise FetchError("The website redirected too many times.", code="http")

    async def _robots_allows(self, url: str) -> bool:
        parts = urlsplit(url)
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        try:
            response, body = await self._get(robots_url, 500_000)
        except FetchError:
            return True  # unreachable robots.txt: no restrictions published
        if response.status_code in (401, 403):
            return False
        if response.status_code >= 400:
            return True
        parser = RobotFileParser()
        parser.parse(body.decode("utf-8", errors="replace").splitlines())
        return parser.can_fetch(USER_AGENT, url)

    async def fetch(self, url: str) -> Page:
        url = await validate_url(url, self._resolver)
        if self._check_robots and not await self._robots_allows(url):
            raise FetchError(
                "This website does not allow automated price checks. Enter the price manually.",
                code="robots",
            )
        response, body = await self._get(url, MAX_BYTES)
        if response.status_code in (401, 403, 429):
            raise FetchError(
                "This website blocks automated price checks. Enter the price manually.",
                code="blocked_by_site",
            )
        if response.status_code >= 400:
            raise FetchError(
                f"The website answered with error {response.status_code}.", code="http"
            )
        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type and content_type not in _HTML_TYPES:
            raise FetchError("That link is not a web page.", code="not_html")
        encoding = response.encoding or "utf-8"
        return Page(str(response.url), response.status_code, body.decode(encoding, "replace"))
