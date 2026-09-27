"""Build the daily CSV in the Ministry of Digital Affairs' 58-column structure.

Structure: "Wzorcowy zakres danych dotyczących cen mieszkań" (22.07.2025),
vendored in reference/. Headers are copied byte-for-byte from that file.
One row per unit on offer: apartments fill columns 36-43, parking spaces
44-47 and storage rooms 48-51; everything that does not apply is "X".
"""

from __future__ import annotations

import csv
import io
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from danegov.config import DEVELOPER, INCLUDE_SOLD, Address, Developer, X
from danegov.models import DaneGovError, PriceRecord, Unit, UnitKind

HEADERS: list[str] = json.loads(
    (Path(__file__).with_name("template_headers.json")).read_text(encoding="utf-8")
)
COLUMN_COUNT = 58
FILE_PREFIX = "Ceny-ofertowe-mieszkan-dewelopera-Trend-Inwestycje"

_KIND_ORDER: dict[UnitKind, int] = {"apartment": 0, "parking": 1, "storage": 2}


class BuildError(DaneGovError):
    pass


def csv_filename(day: date) -> str:
    return f"{FILE_PREFIX}-{day.isoformat()}.csv"


def resource_title(day: date) -> str:
    return f"Ceny ofertowe mieszkań dewelopera Trend Inwestycje {day.isoformat()}"


def _money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}"


def _since(value: date) -> str:
    return f"{value.isoformat()} 00:00:00"


def _address(a: Address, with_unit: bool = True) -> list[str]:
    parts = [a.voivodeship, a.county, a.commune, a.locality, a.street, a.building]
    if with_unit:
        parts.append(a.unit)
    return [*parts, a.postal_code]


def _developer_columns(dev: Developer) -> list[str]:
    return [
        dev.name,
        dev.legal_form,
        dev.krs,
        dev.ceidg,
        dev.nip,
        dev.regon,
        dev.phone,
        dev.email,
        dev.fax,
        dev.website,
        *_address(dev.seat),
        *_address(dev.sales_office),
        dev.extra_sales_locations,
        dev.contact_method,
        *_address(dev.investment_location, with_unit=False),
    ]


def unit_row(unit: Unit, record: PriceRecord, dev: Developer = DEVELOPER) -> list[str]:
    apartment = [X] * 8  # columns 36-43
    parking = [X] * 4  # columns 44-47
    storage = [X] * 4  # columns 48-51
    if unit.kind == "apartment":
        if record.price_m2 is None or record.since_m2 is None:
            raise BuildError(f"{unit.key}: apartment without a price per m²")
        apartment = [
            "Lokal mieszkalny",
            unit.number,
            _money(record.price_m2),
            _since(record.since_m2),
            _money(record.price_total),
            _since(record.since_total),
            X,  # price incl. other components (art. 19a ust. 1 pkt 1-3): none apply
            X,
        ]
    elif unit.kind == "parking":
        parking = [
            "Miejsce postojowe",
            unit.number,
            _money(record.price_total),
            _since(record.since_total),
        ]
    else:
        storage = [
            "Komórka lokatorska",
            unit.number,
            _money(record.price_total),
            _since(record.since_total),
        ]
    rights = [X] * 3  # columns 52-54: no rights needed to use the unit are charged
    other_fees = [X] * 3  # columns 55-57: no other payments to the developer
    row = [
        *_developer_columns(dev),
        *apartment,
        *parking,
        *storage,
        *rights,
        *other_fees,
        dev.prospectus_url,
    ]
    if len(row) != COLUMN_COUNT:
        raise BuildError(f"{unit.key}: row has {len(row)} columns, expected {COLUMN_COUNT}")
    # Keep every field splittable on ";" even by readers that ignore CSV quoting.
    bad = [value for value in row if ";" in value or "\n" in value or "\r" in value]
    if bad:
        raise BuildError(f"{unit.key}: field contains ';' or a line break: {bad[0]!r}")
    return row


def _unit_sort_key(unit: Unit) -> tuple[int, int, str]:
    return (
        _KIND_ORDER[unit.kind],
        int(unit.number) if unit.number.isdigit() else 10**9,
        unit.number,
    )


def published_units(units: list[Unit]) -> list[Unit]:
    selected = units if INCLUDE_SOLD else [u for u in units if u.on_offer]
    return sorted(selected, key=_unit_sort_key)


def build_csv(units: list[Unit], records: dict[str, PriceRecord]) -> bytes:
    if len(HEADERS) != COLUMN_COUNT:
        raise BuildError(f"template has {len(HEADERS)} headers, expected {COLUMN_COUNT}")
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(HEADERS)
    for unit in published_units(units):
        record = records.get(unit.key)
        if record is None:
            raise BuildError(f"{unit.key}: no price record")
        writer.writerow(unit_row(unit, record))
    return buffer.getvalue().encode("utf-8")
