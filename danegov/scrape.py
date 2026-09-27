"""Read the price tables the sales team maintains in WordPress (TablePress).

The public pages are read instead of the WordPress admin, so the pipeline
needs no WordPress credentials and publishes exactly what buyers see.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable

import httpx
from bs4 import BeautifulSoup

from danegov.config import TABLES, TableSource
from danegov.models import DaneGovError, Unit, UnitKind
from danegov.parsing import ParseError, parse_amount, parse_status

logger = logging.getLogger(__name__)

HeaderMatch = Callable[[str], bool]

# Columns are located by header text, not position, so reordering columns in
# TablePress does not silently shift prices into the wrong field.
COLUMNS: dict[UnitKind, dict[str, HeaderMatch]] = {
    "apartment": {
        "number": lambda h: h == "nr",
        "area_m2": lambda h: h in ("m²", "m2", "metraż", "powierzchnia"),
        "price_total": lambda h: h.startswith("cena brutto"),
        "price_m2": lambda h: h.startswith("cena/m") or h.startswith("cena za m"),
        "status": lambda h: h == "status",
    },
    "parking": {
        "number": lambda h: h.startswith("miejsce parkingowe") or h == "nr",
        "price_total": lambda h: h == "cena",
        "status": lambda h: h == "status",
    },
    "storage": {
        "number": lambda h: h.startswith("nr kom") or h == "nr",
        "price_total": lambda h: h == "cena",
        "status": lambda h: h == "status",
    },
}

# Guard against a half-deleted table being published as the day's offer.
MIN_ROWS: dict[UnitKind, int] = {"apartment": 40, "parking": 20, "storage": 20}


class ScrapeError(DaneGovError):
    pass


def _norm_header(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip().lower()


def extract_table(html: str, table_id: int) -> list[list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id=f"tablepress-{table_id}")
    if table is None:
        raise ScrapeError(f"table tablepress-{table_id} not found on page")
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        rows.append([cell.get_text(" ", strip=True).replace("\xa0", " ") for cell in cells])
    if not rows:
        raise ScrapeError(f"table tablepress-{table_id} is empty")
    return rows


def _column_index(headers: list[str], kind: UnitKind) -> dict[str, int]:
    normalized = [_norm_header(h) for h in headers]
    index: dict[str, int] = {}
    for field, matches in COLUMNS[kind].items():
        found = [i for i, h in enumerate(normalized) if matches(h)]
        if not found:
            raise ScrapeError(f"{kind} table: no column for {field!r} in headers {headers}")
        index[field] = found[0]
    return index


def parse_units(kind: UnitKind, rows: list[list[str]]) -> list[Unit]:
    headers, body = rows[0], rows[1:]
    cols = _column_index(headers, kind)
    units: list[Unit] = []
    seen: set[str] = set()
    for line, row in enumerate(body, start=2):
        if not any(cell.strip() for cell in row):
            continue
        cell = {field: (row[i].strip() if i < len(row) else "") for field, i in cols.items()}
        number = cell["number"]
        if not number:
            raise ScrapeError(f"{kind} table row {line}: missing unit number in {row}")
        if number in seen:
            raise ScrapeError(f"{kind} table: duplicate unit number {number!r}")
        seen.add(number)
        try:
            unit = Unit(
                kind=kind,
                number=number,
                status=parse_status(cell["status"]),
                price_total=parse_amount(cell["price_total"]),
                price_m2=parse_amount(cell["price_m2"]) if "price_m2" in cell else None,
                area_m2=parse_amount(cell["area_m2"]) if "area_m2" in cell else None,
            )
        except ParseError as exc:
            raise ScrapeError(f"{kind} {number} (row {line}): {exc}") from exc
        units.append(unit)
    if len(units) < MIN_ROWS[kind]:
        raise ScrapeError(
            f"{kind} table has only {len(units)} units (expected at least {MIN_ROWS[kind]});"
            " refusing to publish a truncated offer"
        )
    return units


def price_inconsistencies(units: Iterable[Unit]) -> list[str]:
    """Apartments whose total differs from area x price per m2 by more than 1 PLN."""
    problems: list[str] = []
    for unit in units:
        if unit.price_m2 is None or unit.area_m2 is None:
            continue
        expected = unit.area_m2 * unit.price_m2
        if abs(expected - unit.price_total) > 1:
            problems.append(
                f"{unit.key}: {unit.area_m2} m² x {unit.price_m2} = {expected:.2f}"
                f" but total is {unit.price_total}"
            )
    return problems


def fetch_pages(client: httpx.Client, sources: Iterable[TableSource]) -> dict[str, str]:
    pages: dict[str, str] = {}
    for url in dict.fromkeys(s.page_url for s in sources):
        try:
            response = client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ScrapeError(f"cannot fetch {url}: {exc}") from exc
        pages[url] = response.text
    return pages


def units_from_pages(pages: dict[str, str], sources: Iterable[TableSource] = TABLES) -> list[Unit]:
    units: list[Unit] = []
    for source in sources:
        rows = extract_table(pages[source.page_url], source.table_id)
        parsed = parse_units(source.kind, rows)
        logger.info(
            "parsed table",
            extra={"kind": source.kind, "table_id": source.table_id, "units": len(parsed)},
        )
        units.extend(parsed)
    return units


def scrape_units(client: httpx.Client) -> list[Unit]:
    return units_from_pages(fetch_pages(client, TABLES))
