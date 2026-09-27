"""Price history: remembers since when each price applies.

The website only shows current prices, so the date a price changed is the
first day the pipeline saw it. That date fills the "Data od której obowiązuje
cena" columns and must survive between runs, hence it is committed to git.
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel

from danegov.models import PriceChange, PriceRecord, Unit, UnitKind
from danegov.parsing import parse_amount

logger = logging.getLogger(__name__)


class PriceState(BaseModel):
    updated: date | None = None
    units: dict[str, PriceRecord] = {}


class PublishedDay(BaseModel):
    resource_id: str
    dataset_id: str | None = None
    uploaded_at: datetime | None = None
    verified_at: datetime | None = None


class PublishedLog(BaseModel):
    days: dict[date, PublishedDay] = {}


def load_prices(path: Path) -> PriceState:
    if not path.exists():
        return PriceState()
    return PriceState.model_validate_json(path.read_text(encoding="utf-8"))


def save_prices(state: PriceState, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = state.model_copy(update={"units": dict(sorted(state.units.items(), key=_sort_key))})
    path.write_text(ordered.model_dump_json(indent=2) + "\n", encoding="utf-8")


def load_published(path: Path) -> PublishedLog:
    if not path.exists():
        return PublishedLog()
    return PublishedLog.model_validate_json(path.read_text(encoding="utf-8"))


def save_published(log: PublishedLog, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(log.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _sort_key(item: tuple[str, PriceRecord]) -> tuple[str, int, str]:
    kind, _, number = item[0].partition(":")
    return (kind, int(number) if number.isdigit() else 10**9, number)


def apply_prices(
    state: PriceState, units: list[Unit], today: date
) -> tuple[PriceState, list[PriceChange]]:
    """Return the state updated with today's website prices and what changed."""
    records = dict(state.units)
    changes: list[PriceChange] = []
    for unit in units:
        previous = records.get(unit.key)
        if previous is None:
            records[unit.key] = PriceRecord(
                price_total=unit.price_total,
                since_total=today,
                price_m2=unit.price_m2,
                since_m2=today if unit.price_m2 is not None else None,
            )
            changes.append(PriceChange(key=unit.key, field="new", old=None, new=unit.price_total))
            continue
        record = previous.model_copy()
        if unit.price_total != previous.price_total:
            changes.append(
                PriceChange(
                    key=unit.key,
                    field="price_total",
                    old=previous.price_total,
                    new=unit.price_total,
                )
            )
            record.price_total, record.since_total = unit.price_total, today
        if unit.price_m2 is not None and unit.price_m2 != previous.price_m2:
            changes.append(
                PriceChange(
                    key=unit.key, field="price_m2", old=previous.price_m2, new=unit.price_m2
                )
            )
            record.price_m2, record.since_m2 = unit.price_m2, today
        records[unit.key] = record
    return PriceState(updated=today, units=records), changes


_LEGACY_KINDS: dict[str, UnitKind] = {
    "mieszkanie": "apartment",
    "miejsce parkingowe": "parking",
    "komórka lokatorska": "storage",
}


def seed_from_legacy_csv(path: Path) -> PriceState:
    """Build the initial state from the hand-maintained data.csv (25 columns).

    Keeps the dates already published on dane.gov.pl for prices that did not
    change, so history stays continuous across the switch.
    """
    records: dict[str, PriceRecord] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            kind = _LEGACY_KINDS.get(row["Typ nieruchomości"].strip())
            if kind is None:
                logger.info("seed skips unit", extra={"type": row["Typ nieruchomości"]})
                continue
            number = row[
                "Nr mieszkania/miejsca parkingowego/komórki lokatorskiej/lokalu usługowego"
            ]
            since_total = _legacy_date(row["Data od której obowiązuje cena mieszkania"])
            records[f"{kind}:{number.strip()}"] = PriceRecord(
                price_total=parse_amount(row["Cena mieszkania (PLN)"]),
                since_total=since_total,
                price_m2=parse_amount(row["Cena za m2 (PLN)"]) if kind == "apartment" else None,
                since_m2=(
                    _legacy_date(row["Data od której obowiązuje cena za m2"])
                    if kind == "apartment"
                    else None
                ),
            )
    return PriceState(updated=None, units=records)


def _legacy_date(text: str) -> date:
    return datetime.strptime(text.strip(), "%Y/%m/%d").date()


def dump_changes(changes: list[PriceChange]) -> list[dict[str, str | None]]:
    return [json.loads(change.model_dump_json()) for change in changes]
