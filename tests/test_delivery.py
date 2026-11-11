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


def test_day_defaults_to_today_and_rejects_the_future(monkeypatch: pytest.MonkeyPatch) -> None:
    import argparse

    from danegov import cli
    from danegov.cli import ConfigError, _day

    monkeypatch.setattr(cli, "_today", lambda: TODAY)
    assert _day(argparse.Namespace()) == TODAY
    assert _day(argparse.Namespace(day=None)) == TODAY
    assert _day(argparse.Namespace(day=date(2026, 9, 27))) == date(2026, 9, 27)
    with pytest.raises(ConfigError):
        _day(argparse.Namespace(day=date(2026, 9, 29)))


def test_portal_retries_network_errors_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from danegov import portal

    monkeypatch.setattr(portal, "RETRY_DELAY_SECONDS", 0)
    calls: list[str] = []

    def flaky(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if len(calls) < 3:
            raise httpx.ProxyError("tunnel failed")
        return httpx.Response(200, content=b"csv")

    with httpx.Client(transport=httpx.MockTransport(flaky)) as client:
        assert Portal(client).download("1") == b"csv"
    assert len(calls) == 3

    def down(request: httpx.Request) -> httpx.Response:
        calls.append("down")
        raise httpx.ConnectTimeout("timed out")

    calls.clear()
    with httpx.Client(transport=httpx.MockTransport(down)) as client:
        with pytest.raises(portal.PortalError):
            Portal(client).resource("1")
    assert len(calls) == portal.ATTEMPTS

    def missing(request: httpx.Request) -> httpx.Response:
        calls.append("404")
        return httpx.Response(404)

    calls.clear()
    with httpx.Client(transport=httpx.MockTransport(missing)) as client:
        with pytest.raises(portal.PortalError):
            Portal(client).resource("1")
    assert calls == ["404"]
