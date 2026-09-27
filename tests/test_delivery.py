from datetime import date, datetime, timezone

import httpx
import pytest

from danegov.cli import decide_delivery
from danegov.portal import Portal
from danegov.state import PublishedDay

TODAY = date(2026, 9, 28)  # Warsaw publication date
NIGHT_BEFORE = datetime(2026, 9, 27, 23, 17, tzinfo=timezone.utc)  # already the 28th in Warsaw
EARLY = datetime(2026, 9, 28, 5, 17, tzinfo=timezone.utc)
MORNING = datetime(2026, 9, 28, 6, 30, tzinfo=timezone.utc)
LATE = datetime(2026, 9, 28, 9, 17, tzinfo=timezone.utc)
RECORDED = PublishedDay(resource_id="2701563")


def _decide(found: str | None = None, **kwargs: object) -> tuple[str, list[int]]:
    calls: list[int] = []

    def lookup() -> str | None:
        calls.append(1)
        return found

    arguments = {
        "force": False,
        "recorded": None,
        "harvester": True,
        "now_utc": EARLY,
        "today": TODAY,
        **kwargs,
    }
    action, _, _ = decide_delivery(lookup=lookup, **arguments)
    return action, calls


@pytest.mark.parametrize(
    ("kwargs", "found", "expected"),
    [
        ({"force": True, "recorded": RECORDED}, None, "upload"),
        ({"recorded": RECORDED}, None, "skip"),
        ({"harvester": False}, None, "upload"),
        ({"now_utc": NIGHT_BEFORE}, None, "wait"),
        ({"now_utc": EARLY}, None, "wait"),
        ({"now_utc": MORNING}, "2800000", "record"),
        ({"now_utc": MORNING}, None, "wait"),
        ({"now_utc": LATE}, "2800000", "record"),
        ({"now_utc": LATE}, None, "upload"),
    ],
)
def test_decide_delivery(kwargs: dict, found: str | None, expected: str) -> None:
    action, _ = _decide(found, **kwargs)
    assert action == expected


def test_admin_lookup_only_when_needed() -> None:
    assert _decide(recorded=RECORDED)[1] == []
    assert _decide(harvester=False)[1] == []
    assert _decide(now_utc=EARLY)[1] == []
    assert _decide(now_utc=LATE)[1] == [1]


def test_resource_by_id_reads_dataset() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/1.4/resources/2701563"
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": "2701563",
                    "attributes": {
                        "title": "Ceny ofertowe mieszkań dewelopera Trend Inwestycje 2026-09-27",
                        "created": "2026-09-27T15:13:19Z",
                    },
                    "relationships": {"dataset": {"data": {"type": "dataset", "id": "16658"}}},
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        resource = Portal(client).resource("2701563")
    assert resource.dataset_id == "16658"
    assert resource.web_url == "https://dane.gov.pl/pl/dataset/16658/resource/2701563"
    assert resource.created.date() == date(2026, 9, 27)
