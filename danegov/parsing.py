"""Parsing of the free-form numbers and statuses typed into TablePress."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from danegov.models import DaneGovError, Status


class ParseError(DaneGovError):
    pass


_NOISE = re.compile(r"(?i)pln|zł|zl|m²|m2|\s")
_THOUSANDS_COMMA = re.compile(r"\d{1,3}(,\d{3})+")
_THOUSANDS_DOT = re.compile(r"\d{1,3}(\.\d{3})+")

_STATUSES: dict[str, Status] = {
    "wolne": "wolne",
    "wolny": "wolne",
    "wolna": "wolne",
    "dostępne": "wolne",
    "dostępny": "wolne",
    "rezerwacja": "rezerwacja",
    "zarezerwowane": "rezerwacja",
    "zarezerwowany": "rezerwacja",
    "sprzedane": "sprzedane",
    "sprzedany": "sprzedane",
    "sprzedana": "sprzedane",
}


def parse_amount(text: str) -> Decimal:
    """Parse amounts as typed on the site.

    Seen in the wild: "312 777,00", "369 265.00", "50.000 PLN",
    "pln5,000.00", "400,000.00 PLN", "7500", "45.33".
    """
    raw = _NOISE.sub("", text)
    if not raw:
        raise ParseError(f"empty amount: {text!r}")
    if "," in raw and "." in raw:
        decimal_sep = "," if raw.rfind(",") > raw.rfind(".") else "."
        thousands_sep = "." if decimal_sep == "," else ","
        raw = raw.replace(thousands_sep, "").replace(decimal_sep, ".")
    elif "," in raw:
        raw = raw.replace(",", "") if _THOUSANDS_COMMA.fullmatch(raw) else raw.replace(",", ".")
    elif "." in raw and _THOUSANDS_DOT.fullmatch(raw):
        raw = raw.replace(".", "")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ParseError(f"not a number: {text!r}") from exc
    if value <= 0:
        raise ParseError(f"amount must be positive: {text!r}")
    return value


def parse_status(text: str) -> Status:
    normalized = text.strip().lower()
    try:
        return _STATUSES[normalized]
    except KeyError as exc:
        allowed = ", ".join(sorted(set(_STATUSES.values())))
        raise ParseError(f"unknown status {text!r} (allowed: {allowed})") from exc
