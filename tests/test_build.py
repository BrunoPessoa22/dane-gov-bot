import csv
import io
from datetime import date
from pathlib import Path

import openpyxl

from danegov.build import HEADERS, build_csv, csv_filename
from danegov.models import Unit
from danegov.state import PriceState, apply_prices

REFERENCE = Path(__file__).parent.parent / "reference"
TODAY = date(2026, 9, 27)


def _rows(units: list[Unit]) -> list[list[str]]:
    state, _ = apply_prices(PriceState(), units, TODAY)
    content = build_csv(units, state.units)
    return list(csv.reader(io.StringIO(content.decode("utf-8")), delimiter=";"))


def test_headers_are_the_ministry_template_verbatim() -> None:
    sheet = openpyxl.load_workbook(
        REFERENCE / "Wzorcowy_zakres_danych_dotyczacych_cen_mieszkan_2025-07-22.xlsx"
    ).worksheets[0]
    assert HEADERS == [cell.value for cell in sheet[1]]
    assert len(HEADERS) == 58


def test_every_row_has_58_columns(units: list[Unit]) -> None:
    rows = _rows(units)
    assert rows[0] == HEADERS
    assert {len(row) for row in rows} == {58}


def test_only_units_on_offer_are_published(units: list[Unit]) -> None:
    rows = _rows(units)[1:]
    offered = [u for u in units if u.status != "sprzedane"]
    assert len(rows) == len(offered)
    numbers = {row[36] for row in rows if row[35] == "Lokal mieszkalny"}
    assert "1" not in numbers  # apartment 1 is sold


def test_apartment_row(units: list[Unit]) -> None:
    row = next(r for r in _rows(units)[1:] if r[35] == "Lokal mieszkalny" and r[36] == "2")
    assert row[37:43] == [
        "7500.00",
        "2026-09-27 00:00:00",
        "342525.00",
        "2026-09-27 00:00:00",
        "X",
        "X",
    ]
    assert row[43:57] == ["X"] * 14
    assert row[18:26] == [
        "kujawsko-pomorskie",
        "brodnicki",
        "Brodnica",
        "Brodnica",
        "ul. Wyspiańskiego",
        "10",
        "X",
        "87-300",
    ]
    assert row[28:35] == [
        "kujawsko-pomorskie",
        "brodnicki",
        "Brodnica",
        "Brodnica",
        "ul. Matejki",
        "X",
        "87-300",
    ]
    assert row[57] == "http://apartamenty-matejki.pl/prospekt-informacyjny/"


def test_parking_and_storage_rows(units: list[Unit]) -> None:
    rows = _rows(units)[1:]
    parking = next(r for r in rows if r[43] == "Miejsce postojowe")
    assert parking[35:43] == ["X"] * 8
    assert parking[45] == "50000.00"
    storage = [r for r in rows if r[47] == "Komórka lokatorska"]
    for row in storage:
        assert row[35:47] == ["X"] * 12


def test_file_is_crlf_utf8_without_bom(units: list[Unit]) -> None:
    state, _ = apply_prices(PriceState(), units, TODAY)
    content = build_csv(units, state.units)
    assert not content.startswith(b"\xef\xbb\xbf")
    assert content.count(b"\r\n") == len(_rows(units))


def test_filename() -> None:
    assert (
        csv_filename(TODAY) == "Ceny-ofertowe-mieszkan-dewelopera-Trend-Inwestycje-2026-09-27.csv"
    )
