from decimal import Decimal

import pytest

from danegov.parsing import ParseError, parse_amount, parse_status


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("312\xa0777,00", "312777.00"),
        ("342 525,00", "342525.00"),
        ("369 265.00", "369265.00"),
        ("50.000 PLN", "50000"),
        ("pln5,000.00", "5000.00"),
        ("400,000.00 PLN", "400000.00"),
        ("7500", "7500"),
        ("45.33", "45.33"),
        ("5 990 zł", "5990"),
    ],
)
def test_parse_amount_formats_seen_on_site(text: str, expected: str) -> None:
    assert parse_amount(text) == Decimal(expected)


@pytest.mark.parametrize("text", ["", "  ", "abc", "0", "-5"])
def test_parse_amount_rejects_garbage(text: str) -> None:
    with pytest.raises(ParseError):
        parse_amount(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("Wolne", "wolne"), (" rezerwacja ", "rezerwacja"), ("SPRZEDANE", "sprzedane")],
)
def test_parse_status(text: str, expected: str) -> None:
    assert parse_status(text) == expected


def test_parse_status_unknown_fails_loudly() -> None:
    with pytest.raises(ParseError, match="unknown status"):
        parse_status("promocja")
