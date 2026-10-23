from decimal import Decimal

import pytest

from app.market.extract import Availability, Method, extract, parse_amount


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1,499.00", "1499.00"), ("1499", "1499"), ("Rs. 74,999", "74999"), ("1.499,00", "1499.00"),
        ("2,50", "2.50"), ("74,999.50", "74999.50"), ("1 299,99", "1299.99"), (1499.0, "1499.0"),
        (12, "12"),
    ],
)  # fmt: skip
def test_parse_amount(raw: object, expected: str) -> None:
    assert parse_amount(raw) == Decimal(expected)


@pytest.mark.parametrize("raw", ["abc", "0", "-5", "- 12.00", True, None, ""])
def test_parse_amount_rejects(raw: object) -> None:
    assert parse_amount(raw) is None


JSON_LD = """
<html><head><title>Ignored title</title>
<meta property="og:title" content="Acme Laptop 14 &amp; Bag">
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
  {"@type":"BreadcrumbList","itemListElement":[]},
  {"@type":["Product","Thing"],"name":"Acme Laptop 14",
   "offers":{"@type":"Offer","price":"74999.00","priceCurrency":"INR",
             "availability":"https://schema.org/InStock"}}]}
</script></head><body>Visible price ₹1 — never scraped</body></html>
"""


def test_json_ld_product_with_graph() -> None:
    result = extract(JSON_LD)
    assert result.title == "Acme Laptop 14 & Bag"
    best = result.best
    assert best is not None
    assert (best.amount, best.currency, best.method) == (Decimal("74999.00"), "INR", Method.JSON_LD)
    assert best.availability is Availability.IN_STOCK and best.confidence == "high"
    assert best.name == "Acme Laptop 14"


def test_aggregate_offer_low_price_is_low_confidence() -> None:
    html = """<script type="application/ld+json">[{"@type":"Product","name":"Phone",
      "offers":{"@type":"AggregateOffer","lowPrice":"499.99","highPrice":"699","priceCurrency":"USD",
      "availability":"OutOfStock"}}]</script>"""
    best = extract(html).best
    assert best is not None and best.low and best.confidence == "low"
    assert best.amount == Decimal("499.99") and best.availability is Availability.OUT_OF_STOCK


def test_price_specification_and_preorder() -> None:
    html = """<script type="application/ld+json">{"@type":"Product","offers":{"@type":"Offer",
      "priceSpecification":{"price":1999,"priceCurrency":"eur"},"availability":"PreOrder"}}</script>"""
    best = extract(html).best
    assert best is not None and (best.amount, best.currency) == (Decimal("1999"), "EUR")
    assert best.availability is Availability.PREORDER


def test_microdata_from_attributes_and_text() -> None:
    attr = (
        '<div itemscope itemtype="https://schema.org/Product">'
        '<span itemprop="name">Kettle</span><meta itemprop="price" content="1,299">'
        '<meta itemprop="priceCurrency" content="INR"></div>'
    )
    text = '<span itemprop="price">£24.50</span><span itemprop="priceCurrency">GBP</span>'
    for html, amount, cur in ((attr, "1299", "INR"), (text, "24.50", "GBP")):
        best = extract(html).best
        assert best is not None and best.method is Method.MICRODATA
        assert (best.amount, best.currency) == (Decimal(amount), cur)


def test_opengraph_product_meta() -> None:
    html = (
        '<meta property="og:title" content="Desk"><meta property="product:price:amount" '
        'content="349.00"><meta property="product:price:currency" content="SGD">'
    )
    best = extract(html).best
    assert best is not None and best.method is Method.OPENGRAPH and best.currency == "SGD"


def test_json_ld_preferred_over_meta_and_no_price_found() -> None:
    both = JSON_LD.replace(
        "</head>",
        '<meta property="product:price:amount" content="1">'
        '<meta property="product:price:currency" content="INR"></head>',
    )
    result = extract(both)
    assert len(result.candidates) == 2 and result.best is not None
    assert result.best.method is Method.JSON_LD

    nothing = extract("<html><title> Just  a page </title><p>₹999 only!</p></html>")
    assert nothing.best is None and nothing.title == "Just a page"


def test_robust_to_malformed_and_unsupported_input() -> None:
    ld = '<script type="application/ld+json">{}</script>'
    bad = "".join(
        [
            ld.format("{not json"),
            ld.format('{"@type":"Product","offers":{"price":"10","priceCurrency":"XYZ"}}'),
            ld.format('{"@type":"Product","offers":{"price":"-3","priceCurrency":"USD"}}'),
            "<div><<<<",
        ]
    )
    assert extract(bad).candidates == []
    assert extract("").best is None
