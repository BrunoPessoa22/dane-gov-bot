from datetime import date, datetime, timezone

import httpx
import pytest

from danegov.cli import decide_upload
from danegov.portal import Portal, PortalResource
from danegov.state import PublishedDay

EARLY = datetime(2026, 9, 28, 5, 17, tzinfo=timezone.utc)
LATE = datetime(2026, 9, 28, 9, 17, tzinfo=timezone.utc)
RECORDED = PublishedDay(resource_id="2701563")
LISTED = [
    PortalResource(id="1", dataset_id="16658", title="x 2026-09-28", created="2026-09-28T01:00:00Z")
]


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"force": True, "recorded": RECORDED}, True),
        ({"recorded": RECORDED}, False),
        ({"listed": LISTED}, False),
        ({"mode": "bot"}, True),
        ({"mode": "harvester", "now_utc": LATE}, False),
        ({"harvester": False}, True),
        ({"harvester": True, "now_utc": EARLY}, False),
        ({"harvester": True, "now_utc": LATE}, True),
    ],
)
def test_decide_upload(kwargs: dict, expected: bool) -> None:
    arguments = {
        "force": False,
        "recorded": None,
        "listed": [],
        "mode": "auto",
        "harvester": False,
        "now_utc": EARLY,
        **kwargs,
    }
    upload, reason = decide_upload(**arguments)
    assert upload is expected, reason


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
