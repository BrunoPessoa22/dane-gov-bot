"""Static facts about the developer and the investment, plus pipeline settings.

Everything published to dane.gov.pl that does not come from the website's
price tables lives here, so a change of address or phone is a one-line edit.
"""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from danegov.models import UnitKind

X = "X"  # dane.gov.pl "znak umowny": position impossible or pointless to fill


class Address(BaseModel):
    voivodeship: str
    county: str
    commune: str
    locality: str
    street: str
    building: str
    unit: str = X
    postal_code: str


class Developer(BaseModel):
    name: str
    legal_form: str
    krs: str
    ceidg: str
    nip: str
    regon: str
    phone: str
    email: str
    fax: str
    website: str
    seat: Address
    sales_office: Address
    extra_sales_locations: str
    contact_method: str
    investment_name: str
    investment_location: Address
    investment_page_url: str
    prospectus_url: str


class TableSource(BaseModel):
    kind: UnitKind
    page_url: str
    table_id: int


DEVELOPER = Developer(
    name="TREND INWESTYCJE",
    legal_form="Spółka cywilna",
    krs=X,
    ceidg=X,
    nip="5691893901",
    regon="380581092",
    phone="604527865",
    email="czai333@poczta.onet.pl",
    fax=X,
    website="http://apartamenty-matejki.pl/",
    seat=Address(
        voivodeship="mazowieckie",
        county="mławski",
        commune="Mława",
        locality="Mława",
        street="Uniszki-Cegielnia",
        building="29",
        postal_code="06-500",
    ),
    sales_office=Address(
        voivodeship="kujawsko-pomorskie",
        county="brodnicki",
        commune="Brodnica",
        locality="Brodnica",
        street="ul. Wyspiańskiego",
        building="10",
        postal_code="87-300",
    ),
    extra_sales_locations=X,
    contact_method=(
        "Telefonicznie: +48 505 893 001, +48 604 527 865, "
        "e-mail: biuro@apartamenty-matejki.pl, "
        "osobiście w biurze sprzedaży: ul. Wyspiańskiego 10, 87-300 Brodnica"
    ),
    investment_name="Apartamenty Matejki",
    # The building has no street number yet (under construction).
    investment_location=Address(
        voivodeship="kujawsko-pomorskie",
        county="brodnicki",
        commune="Brodnica",
        locality="Brodnica",
        street="ul. Matejki",
        building=X,
        postal_code="87-300",
    ),
    investment_page_url="http://apartamenty-matejki.pl/mieszkania/",
    prospectus_url="http://apartamenty-matejki.pl/prospekt-informacyjny/",
)

# The website's TablePress tables are the single source of truth for prices.
# Table 6 (the commercial unit) is left out: the dane.gov.pl structure only
# covers residential units and their parking spaces / storage rooms.
TABLES: tuple[TableSource, ...] = (
    TableSource(
        kind="apartment",
        page_url="http://apartamenty-matejki.pl/mieszkania/",
        table_id=1,
    ),
    TableSource(
        kind="parking",
        page_url="http://apartamenty-matejki.pl/technologia-budynku/",
        table_id=3,
    ),
    TableSource(
        kind="storage",
        page_url="http://apartamenty-matejki.pl/technologia-budynku/",
        table_id=4,
    ),
)

# "Ceny ofertowe" are offer prices: units sold with a notarial deed are no
# longer on offer, so they are left out of the published file.
INCLUDE_SOLD = False

TZ = ZoneInfo("Europe/Warsaw")

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
PRICES_PATH = STATE_DIR / "prices.json"
PUBLISHED_PATH = STATE_DIR / "published.json"
PUBLIC_DIR = ROOT / "public"
CSV_DIR = PUBLIC_DIR / "csv"
XML_PATH = PUBLIC_DIR / "dane-gov.xml"
MD5_PATH = PUBLIC_DIR / "dane-gov.md5"
SUMMARY_PATH = ROOT / "run" / "summary.json"

PAGES_BASE_URL = "https://brunopessoa22.github.io/dane-gov-bot"
REPO_URL = "https://github.com/BrunoPessoa22/dane-gov-bot"

PORTAL_API = "https://api.dane.gov.pl/1.4"
PORTAL_WEB = "https://dane.gov.pl/pl"
INSTITUTION_ID = 5568

# Harvester identifiers (max 36 characters, must never change once registered:
# a new value makes dane.gov.pl re-import everything as new resources).
DATASET_EXT_IDENT = "trend-inwestycje-matejki"

# dane.gov.pl imports registered XML files around 05:50 UTC. Before this hour
# (on the Warsaw publication date) a missing harvester import is not looked for.
HARVEST_READY_UTC_HOUR = 6
# From this hour on, a day the harvester did not import is uploaded by the
# browser bot instead.
HARVEST_FALLBACK_UTC_HOUR = 9

# Must match the cron entries in .github/workflows/daily.yml (checked by tests).
SCHEDULE_UTC: tuple[tuple[int, int], ...] = (
    (23, 17),
    (2, 17),
    (5, 17),
    (9, 17),
    (13, 17),
    (17, 17),
)

EMAIL_FROM = "dane-gov-bot <dane-gov@brunopessoa.com>"
EMAIL_REPLY_TO = "bmpessoa22@gmail.com"
