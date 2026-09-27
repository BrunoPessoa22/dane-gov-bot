from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

from danegov.harvester import NAMESPACE, build_xml, md5_hex, published_days, resource_ext_ident

DAYS = [date(2026, 9, 27), date(2026, 9, 28)]


def test_xml_structure() -> None:
    root = ET.fromstring(build_xml(DAYS, DAYS[-1]))
    assert root.tag == f"{{{NAMESPACE}}}datasets"
    dataset = root.find("dataset")
    assert dataset is not None and dataset.get("status") == "published"
    assert dataset.findtext("updateFrequency") == "daily"
    assert dataset.findtext("categories/category") == "ECON"
    resources = dataset.findall("resources/resource")
    assert [r.findtext("dataDate") for r in resources] == ["2026-09-27", "2026-09-28"]
    first = resources[0]
    assert first.findtext("availability") == "local"
    assert first.findtext("specialSigns/specialSign") == "X"
    assert first.findtext("url").endswith(
        "/csv/Ceny-ofertowe-mieszkan-dewelopera-Trend-Inwestycje-2026-09-27.csv"
    )
    assert first.findtext("title/polish") == (
        "Ceny ofertowe mieszkań dewelopera Trend Inwestycje 2026-09-27"
    )


def test_ext_idents_are_unique_and_short() -> None:
    idents = [resource_ext_ident(d) for d in DAYS]
    assert len(set(idents)) == len(idents)
    assert all(len(i) <= 36 for i in idents)


def test_template_declares_same_namespace() -> None:
    template = (
        Path(__file__).parent.parent / "reference" / "Szablon_budowy_pliku_xml_v1.13_2025-08-21.xml"
    ).read_text(encoding="utf-8")
    assert f'xmlns:ns2="{NAMESPACE}"' in template
    assert f'xmlns:ns2="{NAMESPACE}"' in build_xml(DAYS, DAYS[-1]).decode("utf-8")


def test_md5_is_bare_hex() -> None:
    assert md5_hex(b"abc") == "900150983cd24fb0d6963f7d28e17f72"


def test_published_days_reads_file_names(tmp_path: Path) -> None:
    for name in (
        "Ceny-ofertowe-mieszkan-dewelopera-Trend-Inwestycje-2026-09-28.csv",
        "Ceny-ofertowe-mieszkan-dewelopera-Trend-Inwestycje-2026-09-27.csv",
        "notes.csv",
    ):
        (tmp_path / name).write_text("x")
    assert published_days(tmp_path) == DAYS
