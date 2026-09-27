"""E-mail report of each publication run, sent through Resend.

Recipients come from the NOTIFY_EMAILS secret (comma-separated), never from
the repository, because the repository is public.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx

from danegov.config import EMAIL_FROM, EMAIL_REPLY_TO, SCHEDULE_UTC, TZ
from danegov.models import KIND_LABELS_PL, DaneGovError

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"


class NotifyError(DaneGovError):
    pass


def _pln(value: str | None) -> str:
    if value is None:
        return "-"
    amount = Decimal(value).quantize(Decimal("0.01"))
    whole, _, cents = f"{amount:,.2f}".partition(".")
    return f"{whole.replace(',', ' ')},{cents} zł"


_LABELS: dict[str, str] = dict(KIND_LABELS_PL)


def _unit_label(key: str) -> str:
    kind, _, number = key.partition(":")
    return f"{_LABELS.get(kind, kind)} {number}"


def next_attempt(now: datetime) -> str:
    """Local (Warsaw) time of the next scheduled run."""
    now_utc = now.astimezone(timezone.utc)
    slots = []
    for hour, minute in SCHEDULE_UTC:
        slot = now_utc.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if slot <= now_utc:
            slot += timedelta(days=1)
        slots.append(slot)
    return min(slots).astimezone(TZ).strftime("%Y-%m-%d %H:%M")


def _change_lines(changes: list[dict[str, str | None]]) -> list[str]:
    """One line per unit: total price change, with the per-m² change alongside."""
    by_unit: dict[str, dict[str, dict[str, str | None]]] = {}
    for change in changes:
        by_unit.setdefault(str(change["key"]), {})[str(change["field"])] = change
    lines: list[str] = []
    for key, fields in by_unit.items():
        if "new" in fields:
            detail = f"nowa pozycja, {_pln(fields['new']['new'])}"
        elif "price_total" in fields:
            total = fields["price_total"]
            detail = f"cena {_pln(total['old'])} -> {_pln(total['new'])}"
            if "price_m2" in fields:
                m2 = fields["price_m2"]
                detail += f" ({_pln(m2['old'])}/m² -> {_pln(m2['new'])}/m²)"
        else:
            m2 = fields["price_m2"]
            detail = f"cena za m² {_pln(m2['old'])} -> {_pln(m2['new'])}"
        lines.append(f"  - {_unit_label(key)}: {detail}")
    return lines


def compose(summary: dict[str, Any], outcome: str, run_url: str) -> tuple[str, str]:
    day = summary.get("date", "?")
    if outcome == "success":
        counts: dict[str, int] = summary.get("counts", {})
        count_text = ", ".join(f"{label}: {counts.get(kind, 0)}" for kind, label in _LABELS.items())
        change_lines = _change_lines(summary.get("changes", []))
        warnings: list[str] = summary.get("warnings", [])
        verify = summary.get("verify", {})
        lines = [
            f"Ceny Apartamentów Matejki na dzień {day} są opublikowane na dane.gov.pl"
            " i zgadzają się z plikiem wygenerowanym ze strony internetowej.",
            "",
            f"Lokale w ofercie (wolne i zarezerwowane): {count_text}",
            f"Lokale ze zmianą ceny od poprzedniej publikacji: {len(change_lines)}",
            *change_lines,
            *(
                ["", "Uwagi do tabeli cen na stronie:", *(f"  - {w}" for w in warnings)]
                if warnings
                else []
            ),
            "",
            f"Zasób na dane.gov.pl: {verify.get('resource_url', '-')}",
            f"Plik CSV: {summary.get('csv_url', '-')}",
            f"Przebieg: {run_url}",
            "",
            "--",
            f"EN: prices for {day} are live on dane.gov.pl and match the website"
            f" ({sum(counts.values())} units on offer, {len(change_lines)} with a new price).",
        ]
        return f"[dane.gov.pl] OK – ceny z {day} opublikowane", "\n".join(lines)

    error = summary.get("error") or {}
    step = error.get("step", "nieznany krok")
    message = error.get("message", "brak szczegółów – sprawdź logi przebiegu")
    retry = next_attempt(datetime.now(timezone.utc))
    lines = [
        f"Publikacja cen na dane.gov.pl z dnia {day} NIE powiodła się.",
        "",
        f"Krok: {step}",
        f"Błąd: {message}",
        "",
        f"Następna automatyczna próba: {retry} (czas polski).",
        "Jeśli błąd dotyczy tabeli cen na stronie, popraw tabelę w WordPress (TablePress);"
        " kolejna próba opublikuje dane automatycznie.",
        "",
        f"Logi przebiegu: {run_url}",
        "",
        "--",
        f"EN: publication for {day} FAILED at step '{step}': {message}."
        f" Next automatic attempt {retry} Warsaw time. Logs: {run_url}",
    ]
    return f"[dane.gov.pl] BŁĄD – publikacja z {day} wymaga uwagi", "\n".join(lines)


def send(api_key: str, recipients: list[str], subject: str, text: str) -> str:
    if not recipients:
        raise NotifyError("no recipients configured (NOTIFY_EMAILS)")
    try:
        response = httpx.post(
            RESEND_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "dane-gov-bot/2.0",
            },
            json={
                "from": EMAIL_FROM,
                "to": recipients,
                "reply_to": EMAIL_REPLY_TO,
                "subject": subject,
                "text": text,
            },
            timeout=30,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise NotifyError(
            f"Resend rejected the e-mail: {exc.response.status_code} {exc.response.text}"
        ) from exc
    except httpx.HTTPError as exc:
        raise NotifyError(f"Resend request failed: {exc}") from exc
    email_id = str(response.json().get("id", ""))
    logger.info("notification sent", extra={"email_id": email_id, "recipients": len(recipients)})
    return email_id
