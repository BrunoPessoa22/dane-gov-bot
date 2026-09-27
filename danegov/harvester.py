"""XML + MD5 for dane.gov.pl's automatic import ("harwester", schema 1.13).

Follows "Instrukcja przygotowania pliku XML" 1.0.5 (29.09.2025) and the
template in reference/. The XML lists every daily CSV ever published: the
portal only fetches resources whose extIdent it has not seen, and dropping an
entry could unpublish it, so entries are never removed.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

from danegov.build import FILE_PREFIX, resource_title
from danegov.config import DATASET_EXT_IDENT, DEVELOPER, PAGES_BASE_URL
from danegov.models import DaneGovError

NAMESPACE = "urn:otwarte-dane:harvester:1.13"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
LAW = (
    "art. 19b. ust. 1 Ustawy z dnia 20 maja 2021 r. o ochronie praw nabywcy lokalu "
    "mieszkalnego lub domu jednorodzinnego oraz Deweloperskim Funduszu Gwarancyjnym "
    "(Dz. U. z 2024 r. poz. 695)"
)
_CSV_NAME = re.compile(rf"{re.escape(FILE_PREFIX)}-(\d{{4}}-\d{{2}}-\d{{2}})\.csv")


class HarvesterError(DaneGovError):
    pass


def resource_ext_ident(day: date) -> str:
    ident = f"{DATASET_EXT_IDENT}-{day:%Y%m%d}"
    if len(ident) > 36:
        raise HarvesterError(f"extIdent too long ({len(ident)} > 36): {ident}")
    return ident


def published_days(csv_dir: Path) -> list[date]:
    days = [
        date.fromisoformat(match.group(1))
        for path in csv_dir.glob("*.csv")
        if (match := _CSV_NAME.fullmatch(path.name))
    ]
    return sorted(days)


def _text(parent: ET.Element, tag: str, value: str) -> ET.Element:
    element = ET.SubElement(parent, tag)
    element.text = value
    return element


def _bilingual(parent: ET.Element, tag: str, polish: str, english: str) -> None:
    element = ET.SubElement(parent, tag)
    _text(element, "polish", polish)
    _text(element, "english", english)


def _flags(parent: ET.Element, with_protected: bool) -> None:
    _text(parent, "hasDynamicData", "false")
    _text(parent, "hasHighValueData", "true")
    _text(parent, "hasHighValueDataFromEuropeanCommissionList", "false")
    _text(parent, "hasResearchData", "false")
    if with_protected:
        _text(parent, "containsProtectedData", "false")


def _resource(resources: ET.Element, day: date) -> None:
    name = DEVELOPER.name.title()
    resource = ET.SubElement(resources, "resource", status="published")
    _text(resource, "extIdent", resource_ext_ident(day))
    _text(resource, "url", f"{PAGES_BASE_URL}/csv/{FILE_PREFIX}-{day.isoformat()}.csv")
    _bilingual(
        resource,
        "title",
        resource_title(day),
        f"Offer prices for developer's apartments {name} {day.isoformat()}",
    )
    _bilingual(
        resource,
        "description",
        f"Dane dotyczące cen ofertowych mieszkań dewelopera {name} udostępnione "
        f"{day.isoformat()} zgodnie z {LAW}.",
        f"Data on offer prices of apartments of the developer {name} made available "
        f"{day.isoformat()} in accordance with {LAW}.",
    )
    _text(resource, "availability", "local")
    _text(resource, "dataDate", day.isoformat())
    signs = ET.SubElement(resource, "specialSigns")
    _text(signs, "specialSign", "X")
    _flags(resource, with_protected=True)


def build_xml(days: list[date], today: date) -> bytes:
    if not days:
        raise HarvesterError("no published CSV files to list")
    name = DEVELOPER.name.title()
    # Written literally: ElementTree reserves "ns<N>" prefixes, and the ministry
    # template (like every live harvester file) uses "ns2:datasets".
    root = ET.Element("ns2:datasets", {"xmlns:ns2": NAMESPACE, "xmlns:xsi": XSI})
    dataset = ET.SubElement(root, "dataset", status="published")
    _text(dataset, "extIdent", DATASET_EXT_IDENT)
    _bilingual(
        dataset,
        "title",
        f"Ceny ofertowe mieszkań dewelopera {name} w {today.year} r.",
        f"Offer prices of apartments of developer {name} in {today.year}.",
    )
    _bilingual(
        dataset,
        "description",
        f"Zbiór danych zawiera informacje o cenach ofertowych mieszkań dewelopera {name} "
        f"(inwestycja {DEVELOPER.investment_name}) udostępniane zgodnie z {LAW}.",
        f"The dataset contains information on offer prices of apartments of the developer "
        f"{name} (investment {DEVELOPER.investment_name}) made available in accordance "
        f"with {LAW}.",
    )
    _text(dataset, "url", DEVELOPER.investment_page_url)
    _text(dataset, "updateFrequency", "daily")
    _flags(dataset, with_protected=False)
    categories = ET.SubElement(dataset, "categories")
    _text(categories, "category", "ECON")
    resources = ET.SubElement(dataset, "resources")
    for day in days:
        _resource(resources, day)
    tags = ET.SubElement(dataset, "tags")
    tag = _text(tags, "tag", "Deweloper")
    tag.set("lang", "pl")
    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode", xml_declaration=False)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n").encode("utf-8")


def md5_hex(content: bytes) -> str:
    return hashlib.md5(content, usedforsecurity=False).hexdigest()
