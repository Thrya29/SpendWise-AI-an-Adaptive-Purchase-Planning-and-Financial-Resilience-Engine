"""Deterministic money formatting for server-generated text (summaries, explanations)."""

from __future__ import annotations

from app.domain.money import minor_exponent

_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}


def _group(whole: str, indian: bool) -> str:
    if len(whole) <= 3:
        return whole
    if not indian:
        groups = []
        while whole:
            groups.append(whole[-3:])
            whole = whole[:-3]
        return ",".join(reversed(groups))
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.append(head[-2:])
        head = head[:-2]
    if head:
        groups.append(head)
    return ",".join(reversed(groups)) + "," + tail


def format_amount(minor: int, currency: str, *, drop_zero_fraction: bool = True) -> str:
    """e.g. 14999900 INR -> '₹1,49,999'; 150 USD -> '$1.50'; negative values get a leading '-'."""
    exp = minor_exponent(currency)
    sign = "-" if minor < 0 else ""
    digits = str(abs(minor)).rjust(exp + 1, "0")
    whole, frac = (digits[:-exp], digits[-exp:]) if exp else (digits, "")
    text = _group(whole, currency == "INR")
    if frac and not (drop_zero_fraction and set(frac) == {"0"}):
        text += "." + frac
    symbol = _SYMBOLS.get(currency)
    return f"{sign}{symbol}{text}" if symbol else f"{sign}{currency} {text}"
