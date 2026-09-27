from pathlib import Path

import pytest

from danegov.config import TABLES
from danegov.models import Unit
from danegov.scrape import units_from_pages

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def pages() -> dict[str, str]:
    by_slug = {
        "mieszkania": (FIXTURES / "mieszkania.html").read_text(encoding="utf-8"),
        "technologia-budynku": (FIXTURES / "technologia-budynku.html").read_text(encoding="utf-8"),
    }
    return {s.page_url: by_slug[s.page_url.rstrip("/").rsplit("/", 1)[-1]] for s in TABLES}


@pytest.fixture(scope="session")
def units(pages: dict[str, str]) -> list[Unit]:
    return units_from_pages(pages)
