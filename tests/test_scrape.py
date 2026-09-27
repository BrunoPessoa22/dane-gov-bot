from collections import Counter

import pytest

from danegov.models import Unit
from danegov.scrape import ScrapeError, extract_table, parse_units, price_inconsistencies


def test_all_tables_parse(units: list[Unit]) -> None:
    assert Counter(u.kind for u in units) == {"apartment": 56, "parking": 36, "storage": 38}


def test_apartment_fields(units: list[Unit]) -> None:
    apt2 = next(u for u in units if u.key == "apartment:2")
    assert (str(apt2.area_m2), str(apt2.price_m2), str(apt2.price_total)) == (
        "45.67",
        "7500",
        "342525.00",
    )
    assert apt2.status == "wolne"


def test_site_totals_match_area_times_price(units: list[Unit]) -> None:
    assert price_inconsistencies(units) == []


def test_missing_table_is_an_error() -> None:
    with pytest.raises(ScrapeError, match="tablepress-9"):
        extract_table("<html><table id='tablepress-1'></table></html>", 9)


def test_renamed_column_is_an_error() -> None:
    rows = [["Nr", "Metry", "Cena brutto (PLN)", "Cena/m² (PLN)", "Status"]] + [
        [str(i), "40", "280 000,00", "7000", "wolne"] for i in range(50)
    ]
    with pytest.raises(ScrapeError, match="area_m2"):
        parse_units("apartment", rows)


def test_truncated_table_is_an_error() -> None:
    rows = [["Miejsce parkingowe", "Cena", "Status"], ["1", "50.000 PLN", "wolne"]]
    with pytest.raises(ScrapeError, match="truncated"):
        parse_units("parking", rows)


def test_duplicate_numbers_are_an_error() -> None:
    rows = [["Miejsce parkingowe", "Cena", "Status"]] + [["1", "50.000 PLN", "wolne"]] * 2
    with pytest.raises(ScrapeError, match="duplicate"):
        parse_units("parking", rows)
