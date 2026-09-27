from datetime import datetime, timezone

from danegov.notify import compose, next_attempt

SUMMARY = {
    "date": "2026-09-27",
    "counts": {"apartment": 26, "parking": 6, "storage": 0},
    "changes": [
        {"key": "apartment:2", "field": "price_total", "old": "315123.00", "new": "342525.00"},
        {"key": "parking:7", "field": "new", "old": None, "new": "50000"},
    ],
    "csv_url": "https://example.test/x.csv",
    "verify": {"resource_url": "https://dane.gov.pl/pl/dataset/1/resource/2"},
}


def test_success_email_lists_changes() -> None:
    subject, text = compose(SUMMARY, "success", "https://run")
    assert subject == "[dane.gov.pl] OK – ceny z 2026-09-27 opublikowane"
    assert "Mieszkanie 2: cena 315 123,00 zł -> 342 525,00 zł" in text
    assert "Miejsce postojowe 7: nowa pozycja, 50 000,00 zł" in text
    assert "Mieszkanie: 26, Miejsce postojowe: 6, Komórka lokatorska: 0" in text


def test_failure_email_names_step_and_error() -> None:
    summary = {"date": "2026-09-27", "error": {"step": "build", "message": "table missing"}}
    subject, text = compose(summary, "failure", "https://run")
    assert "BŁĄD" in subject
    assert "Krok: build" in text and "Błąd: table missing" in text


def test_failure_email_without_summary() -> None:
    subject, text = compose({}, "failure", "https://run")
    assert "BŁĄD" in subject and "https://run" in text


def test_next_attempt_wraps_to_next_day() -> None:
    late = datetime(2026, 9, 27, 23, 30, tzinfo=timezone.utc)
    assert next_attempt(late) == "2026-09-28 04:17"  # 02:17 UTC in CEST


def test_changes_are_grouped_per_unit() -> None:
    summary = {
        **SUMMARY,
        "changes": [
            {"key": "apartment:2", "field": "price_total", "old": "315123.00", "new": "342525.00"},
            {"key": "apartment:2", "field": "price_m2", "old": "6900", "new": "7500"},
        ],
    }
    _, text = compose(summary, "success", "https://run")
    assert (
        "  - Mieszkanie 2: cena 315 123,00 zł -> 342 525,00 zł"
        " (6 900,00 zł/m² -> 7 500,00 zł/m²)" in text
    )
    assert "Lokale ze zmianą ceny od poprzedniej publikacji: 1" in text
