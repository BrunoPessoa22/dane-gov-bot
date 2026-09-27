import re
from pathlib import Path

from danegov.config import SCHEDULE_UTC

WORKFLOW = Path(__file__).parent.parent / ".github" / "workflows" / "daily.yml"


def test_schedule_matches_config() -> None:
    crons = re.findall(r"cron:\s*'(\d+) (\d+) \* \* \*'", WORKFLOW.read_text(encoding="utf-8"))
    assert sorted((int(h), int(m)) for m, h in crons) == sorted(SCHEDULE_UTC)
