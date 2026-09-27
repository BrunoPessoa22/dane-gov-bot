from datetime import date
from decimal import Decimal
from pathlib import Path

from danegov.models import PriceRecord, Unit
from danegov.state import PriceState, apply_prices, seed_from_legacy_csv

OLD = date(2025, 9, 11)
TODAY = date(2026, 9, 27)


def _apt(price_total: str, price_m2: str) -> Unit:
    return Unit(
        kind="apartment",
        number="2",
        status="wolne",
        price_total=Decimal(price_total),
        price_m2=Decimal(price_m2),
        area_m2=Decimal("45.67"),
    )


def _state() -> PriceState:
    record = PriceRecord(
        price_total=Decimal("315123.00"), since_total=OLD, price_m2=Decimal("6900"), since_m2=OLD
    )
    return PriceState(units={"apartment:2": record})


def test_unchanged_price_keeps_its_date() -> None:
    state, changes = apply_prices(_state(), [_apt("315123.00", "6900")], TODAY)
    assert changes == []
    assert state.units["apartment:2"].since_total == OLD


def test_changed_price_gets_todays_date() -> None:
    state, changes = apply_prices(_state(), [_apt("342525.00", "7500")], TODAY)
    record = state.units["apartment:2"]
    assert (record.since_total, record.since_m2) == (TODAY, TODAY)
    assert {c.field for c in changes} == {"price_total", "price_m2"}


def test_same_value_different_notation_is_not_a_change() -> None:
    _, changes = apply_prices(_state(), [_apt("315123", "6900.00")], TODAY)
    assert changes == []


def test_new_unit_is_recorded() -> None:
    state, changes = apply_prices(PriceState(), [_apt("342525.00", "7500")], TODAY)
    assert changes[0].field == "new"
    assert state.units["apartment:2"].since_total == TODAY


def test_seed_from_legacy_csv_keeps_published_dates() -> None:
    state = seed_from_legacy_csv(Path(__file__).parent / "fixtures" / "legacy_data.csv")
    assert state.units["apartment:1"].since_total == OLD
    assert state.units["apartment:1"].price_total == Decimal("312777.00")
    assert state.units["parking:1"].price_m2 is None
    assert not any(key.startswith("commercial") for key in state.units)
