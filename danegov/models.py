"""Domain models shared across the pipeline."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

UnitKind = Literal["apartment", "parking", "storage"]
Status = Literal["wolne", "rezerwacja", "sprzedane"]

KIND_LABELS_PL: dict[UnitKind, str] = {
    "apartment": "Mieszkanie",
    "parking": "Miejsce postojowe",
    "storage": "Komórka lokatorska",
}


class DaneGovError(Exception):
    """Base class for failures that should stop the run and alert people."""


class Unit(BaseModel):
    """One sellable unit as shown on the website."""

    model_config = ConfigDict(frozen=True)

    kind: UnitKind
    number: str
    status: Status
    price_total: Decimal
    price_m2: Decimal | None = None
    area_m2: Decimal | None = None

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.number}"

    @property
    def on_offer(self) -> bool:
        return self.status != "sprzedane"


class PriceRecord(BaseModel):
    """Current price of a unit and the date from which it applies."""

    price_total: Decimal
    since_total: date
    price_m2: Decimal | None = None
    since_m2: date | None = None


class PriceChange(BaseModel):
    key: str
    field: Literal["new", "price_total", "price_m2"]
    old: Decimal | None
    new: Decimal
