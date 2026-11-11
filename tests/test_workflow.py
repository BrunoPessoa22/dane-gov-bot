import re
from pathlib import Path

from danegov.config import SCHEDULE_UTC

WORKFLOW = Path(__file__).parent.parent / ".github" / "workflows" / "daily.yml"


def test_schedule_matches_config() -> None:
    crons = re.findall(r"cron:\s*'(\d+) (\d+) \* \* \*'", WORKFLOW.read_text(encoding="utf-8"))
    assert sorted((int(h), int(m)) for m, h in crons) == sorted(SCHEDULE_UTC)


def _step(name: str) -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index(f"- name: {name}")
    end = text.find("\n      - ", start + 1)
    return text[start : end if end != -1 else len(text)]


def test_portal_steps_get_the_proxy() -> None:
    # dane.gov.pl only answers Polish IPs; every step that talks to it needs the route.
    for name in ("Deliver to dane.gov.pl", "Verify dane.gov.pl serves today's file"):
        assert "DANE_GOV_PROXY: ${{ secrets.DANE_GOV_PROXY }}" in _step(name)
