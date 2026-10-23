import httpx
import pytest

from app.market.fetcher import FetchError, SafeFetcher, validate_url

PUBLIC = "93.184.215.14"


def resolver_for(mapping: dict[str, list[str]]):
    async def resolve(host: str) -> list[str]:
        if host not in mapping:
            raise OSError("NXDOMAIN")
        return mapping[host]

    return resolve


PUBLIC_DNS = resolver_for({"shop.example": [PUBLIC], "cdn.example": [PUBLIC]})


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("ftp://shop.example/x", "invalid_url"),
        ("javascript:alert(1)", "invalid_url"),
        ("https://user:pw@shop.example/", "invalid_url"),
        ("https://shop.example:8080/", "blocked"),
        ("http://localhost/", "blocked"),
        ("http://printer.local/", "blocked"),
        ("http://127.0.0.1/", "blocked"),
        ("http://10.0.0.5/", "blocked"),
        ("http://192.168.1.1/", "blocked"),
        ("http://169.254.169.254/latest/meta-data/", "blocked"),
        ("http://[::1]/", "blocked"),
        ("http://[::ffff:127.0.0.1]/", "blocked"),
        ("http://0.0.0.0/", "blocked"),
        ("http://nowhere.example/", "dns"),
        ("https://shop.example:99999/", "invalid_url"),
    ],
)
async def test_validate_url_rejects_unsafe_targets(url: str, code: str) -> None:
    with pytest.raises(FetchError) as info:
        await validate_url(url, PUBLIC_DNS)
    assert info.value.code == code


async def test_validate_url_rejects_hosts_resolving_to_private_addresses() -> None:
    sneaky = resolver_for({"db": ["172.18.0.2"], "mixed.example": [PUBLIC, "10.1.1.1"]})
    for url in ("http://db/", "https://mixed.example/"):
        with pytest.raises(FetchError, match="not a public website"):
            await validate_url(url, sneaky)
    assert (
        await validate_url("https://shop.example/p?id=1", PUBLIC_DNS)
        == "https://shop.example/p?id=1"
    )


def fetcher(handler, *, robots: bool = False, dns=PUBLIC_DNS) -> SafeFetcher:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    return SafeFetcher(client, dns, check_robots=robots)


HTML = "<html><title>ok</title></html>"


async def test_fetch_success_and_redirect_revalidation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "https://cdn.example/new"})
        return httpx.Response(200, html=HTML)

    page = await fetcher(handler).fetch("https://shop.example/old")
    assert page.url == "https://cdn.example/new" and page.html == HTML

    def to_metadata(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://169.254.169.254/"})

    with pytest.raises(FetchError) as info:
        await fetcher(to_metadata).fetch("https://shop.example/")
    assert info.value.code == "blocked"


async def test_fetch_limits_and_errors() -> None:
    def loop(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "/again"})

    def huge(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 2_100_000, headers={"content-type": "text/html"})

    def pdf(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF", headers={"content-type": "application/pdf"})

    def forbidden(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    def missing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    def broken_redirect(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302)

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    for handler, code in (
        (loop, "http"), (huge, "too_large"), (pdf, "not_html"), (forbidden, "blocked_by_site"),
        (missing, "http"), (broken_redirect, "http"), (timeout, "timeout"), (refused, "network"),
    ):  # fmt: skip
        with pytest.raises(FetchError) as info:
            await fetcher(handler).fetch("https://shop.example/p")
        assert info.value.code == code, handler.__name__


async def test_robots_txt_is_respected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")
        return httpx.Response(200, html=HTML)

    f = fetcher(handler, robots=True)
    assert (await f.fetch("https://shop.example/public/item")).html == HTML
    with pytest.raises(FetchError) as info:
        await f.fetch("https://shop.example/private/item")
    assert info.value.code == "robots"

    def no_robots(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, html=HTML)

    assert (await fetcher(no_robots, robots=True).fetch("https://shop.example/x")).html == HTML

    def robots_forbidden(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(403)
        return httpx.Response(200, html=HTML)

    with pytest.raises(FetchError, match="does not allow"):
        await fetcher(robots_forbidden, robots=True).fetch("https://shop.example/x")
    await f.aclose()
