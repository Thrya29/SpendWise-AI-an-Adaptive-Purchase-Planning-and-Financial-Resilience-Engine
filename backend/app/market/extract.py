"""Extract a product's price from a page's *structured* data.

Only machine-readable markup that sellers publish on purpose is used (schema.org
JSON-LD, microdata, OpenGraph / product meta tags). Visible text is never
scraped, so a price is either stated by the page or reported as not found.
Pure functions: no network, no I/O.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from html.parser import HTMLParser
from typing import Any

from app.domain.money import SUPPORTED_CURRENCIES

logger = logging.getLogger("spendwise.market")

MAX_JSON_BLOCKS = 20
MAX_JSON_CHARS = 500_000


class Method(StrEnum):
    JSON_LD = "json_ld"
    MICRODATA = "microdata"
    OPENGRAPH = "opengraph"


class Availability(StrEnum):
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    PREORDER = "preorder"
    UNKNOWN = "unknown"


_CONFIDENCE = {Method.JSON_LD: "high", Method.MICRODATA: "medium", Method.OPENGRAPH: "medium"}


@dataclass(frozen=True, slots=True)
class PriceCandidate:
    amount: Decimal  # major units
    currency: str
    method: Method
    availability: Availability = Availability.UNKNOWN
    name: str | None = None
    low: bool = False  # True when it is the low end of a price range (AggregateOffer)

    @property
    def confidence(self) -> str:
        return "low" if self.low else _CONFIDENCE[self.method]


@dataclass(frozen=True, slots=True)
class Extraction:
    title: str | None
    candidates: list[PriceCandidate]

    @property
    def best(self) -> PriceCandidate | None:
        """Highest-confidence candidate; ties go to the first one found."""
        order = {"high": 0, "medium": 1, "low": 2}
        return min(self.candidates, key=lambda c: order[c.confidence], default=None)


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.json_blocks: list[str] = []
        self.meta: dict[str, str] = {}
        self.itemprops: dict[str, str] = {}
        self.title_parts: list[str] = []
        self._in_json = False
        self._in_title = False
        self._pending_prop: str | None = None  # itemprop whose value is the element text
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self._in_json, self._buf = True, []
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            if key and "content" in a:
                self.meta.setdefault(key, a["content"].strip())
        if "itemprop" in a:
            prop = a["itemprop"].lower()
            value = a.get("content") or a.get("value") or a.get("href") or ""
            if value:
                self.itemprops.setdefault(prop, value.strip())
            elif prop in ("price", "pricecurrency"):
                self._pending_prop = prop
                self._buf = []

    def handle_data(self, data: str) -> None:
        if self._in_json:
            self._buf.append(data)
        elif self._in_title:
            self.title_parts.append(data)
        elif self._pending_prop:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_json:
            if len(self.json_blocks) < MAX_JSON_BLOCKS:
                self.json_blocks.append("".join(self._buf)[:MAX_JSON_CHARS])
            self._in_json = False
        elif tag == "title":
            self._in_title = False
        elif self._pending_prop:
            text = "".join(self._buf).strip()
            if text:
                self.itemprops.setdefault(self._pending_prop, text)
            self._pending_prop = None


_NUMBER = re.compile(r"\d[\d,.\s]*")


def parse_amount(raw: object) -> Decimal | None:
    """Parse '1,499.00', '1499', 'Rs. 74,999', '1.499,00' or a number into a Decimal."""
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, int | float):
        raw = repr(raw)
    m = _NUMBER.search(str(raw))
    if not m or str(raw)[: m.start()].rstrip().endswith("-"):
        return None  # no number, or a negative one
    text = m.group(0).strip().replace(" ", "")
    if "," in text and "." in text:
        # Whichever separator comes last is the decimal point.
        text = (
            text.replace(",", "")
            if text.rfind(".") > text.rfind(",")
            else (text.replace(".", "").replace(",", "."))
        )
    elif "," in text:
        whole, _, frac = text.rpartition(",")
        text = f"{whole.replace(',', '')}.{frac}" if len(frac) in (1, 2) else text.replace(",", "")
    try:
        value = Decimal(text.rstrip("."))
    except InvalidOperation:
        return None
    return value if value.is_finite() and value > 0 else None


def _currency(raw: object) -> str | None:
    code = str(raw or "").strip().upper()
    aliases = {"RS": "INR", "RS.": "INR", "₹": "INR", "$": "USD", "€": "EUR", "£": "GBP"}
    code = aliases.get(code, code)
    return code if code in SUPPORTED_CURRENCIES else None


def _availability(raw: object) -> Availability:
    text = str(raw or "").lower()
    if "outofstock" in text or "soldout" in text or "discontinued" in text:
        return Availability.OUT_OF_STOCK
    if "preorder" in text or "presale" in text:
        return Availability.PREORDER
    if "instock" in text or "limitedavailability" in text or "onlineonly" in text:
        return Availability.IN_STOCK
    return Availability.UNKNOWN


def _walk(node: Any) -> list[dict[str, Any]]:
    """Every JSON object in a JSON-LD document (handles lists and @graph)."""
    out: list[dict[str, Any]] = []
    stack = [node]
    while stack and len(out) < 500:
        cur = stack.pop()
        if isinstance(cur, dict):
            out.append(cur)
            stack.extend(v for v in cur.values() if isinstance(v, dict | list))
        elif isinstance(cur, list):
            stack.extend(cur)
    return out


def _types(obj: dict[str, Any]) -> set[str]:
    raw = obj.get("@type", [])
    values = raw if isinstance(raw, list) else [raw]
    return {str(v).rsplit("/", 1)[-1].lower() for v in values}


def _from_json_ld(blocks: list[str]) -> list[PriceCandidate]:
    found: list[PriceCandidate] = []
    for block in blocks:
        try:
            doc = json.loads(block.strip().rstrip(";"))
        except (json.JSONDecodeError, ValueError):
            continue
        for obj in _walk(doc):
            if "product" not in _types(obj):
                continue
            name = obj.get("name") if isinstance(obj.get("name"), str) else None
            offers = obj.get("offers")
            for offer in _walk(offers) if offers is not None else []:
                kinds = _types(offer)
                if not kinds & {"offer", "aggregateoffer"} and "price" not in offer:
                    continue
                currency = _currency(offer.get("priceCurrency"))
                spec = offer.get("priceSpecification")
                if currency is None and isinstance(spec, dict):
                    currency = _currency(spec.get("priceCurrency"))
                low = "aggregateoffer" in kinds and offer.get("price") is None
                raw = offer.get("price") if not low else offer.get("lowPrice")
                if raw is None and isinstance(spec, dict):
                    raw = spec.get("price")
                amount = parse_amount(raw)
                if amount is not None and currency:
                    found.append(
                        PriceCandidate(
                            amount, currency, Method.JSON_LD,
                            _availability(offer.get("availability")), name, low,
                        )
                    )  # fmt: skip
    return found


def extract(html: str) -> Extraction:
    parser = _Collector()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # malformed HTML must never crash ingestion
        logger.debug("html_parse_error", exc_info=True)

    title = (
        parser.meta.get("og:title")
        or parser.meta.get("twitter:title")
        or " ".join("".join(parser.title_parts).split())
        or None
    )
    candidates = _from_json_ld(parser.json_blocks)

    props = parser.itemprops
    amount, currency = parse_amount(props.get("price")), _currency(props.get("pricecurrency"))
    if amount is not None and currency:
        candidates.append(
            PriceCandidate(amount, currency, Method.MICRODATA,
                           _availability(props.get("availability")), props.get("name"))
        )  # fmt: skip

    meta = parser.meta
    for amount_key, currency_key in (
        ("product:price:amount", "product:price:currency"),
        ("og:price:amount", "og:price:currency"),
    ):
        amount, currency = parse_amount(meta.get(amount_key)), _currency(meta.get(currency_key))
        if amount is not None and currency:
            candidates.append(
                PriceCandidate(amount, currency, Method.OPENGRAPH,
                               _availability(meta.get("product:availability")), title)
            )  # fmt: skip
            break
    return Extraction(title=title[:300] if title else None, candidates=candidates)
