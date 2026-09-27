"""Command line entry points used by the GitHub Actions workflow.

    python -m danegov build          scrape the website, write today's CSV + XML + MD5
    python -m danegov plan           tell the workflow whether a browser is needed
    python -m danegov deliver        upload through the admin panel, or record the
                                     harvester's import (never both for one day)
    python -m danegov verify         check dane.gov.pl serves exactly today's CSV
    python -m danegov notify         e-mail the outcome
    python -m danegov seed-state     one-off: initial price history from data.csv

Each command adds its result to run/summary.json, which the notify step
turns into the e-mail.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
import time
from collections.abc import Callable
from contextlib import ExitStack
from datetime import date, datetime
from datetime import time as dt_time
from datetime import timezone
from pathlib import Path
from typing import Any

import httpx
from playwright.sync_api import Page

from danegov import config
from danegov.build import build_csv, csv_filename, published_units, resource_title
from danegov.harvester import build_xml, md5_hex, published_days
from danegov.logs import setup_logging
from danegov.models import DaneGovError
from danegov.notify import compose, send
from danegov.portal import Portal, PortalError, PortalResource
from danegov.scrape import price_inconsistencies, scrape_units
from danegov.state import (
    PublishedDay,
    apply_prices,
    dump_changes,
    load_prices,
    load_published,
    save_prices,
    save_published,
    seed_from_legacy_csv,
)
from danegov.upload import admin_session, find_resource_id, upload_csv

logger = logging.getLogger("danegov")

USER_AGENT = f"dane-gov-bot/2.0 (+{config.REPO_URL})"
BUILDS_PATH = config.STATE_DIR / "builds.json"


class VerifyError(DaneGovError):
    pass


class ConfigError(DaneGovError):
    pass


def _today() -> date:
    return datetime.now(config.TZ).date()


def _http() -> httpx.Client:
    return httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT}, follow_redirects=True)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _github_output(**values: str) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    if not target:
        return
    with open(target, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"environment variable {name} is not set")
    return value


def _delivery_mode() -> str:
    mode = os.environ.get("DELIVERY_MODE", "").strip().lower() or "auto"
    if mode not in ("auto", "bot", "harvester"):
        raise ConfigError(f"DELIVERY_MODE must be auto, bot or harvester, not {mode!r}")
    return mode


def cmd_seed_state(args: argparse.Namespace, summary: dict[str, Any]) -> None:
    if config.PRICES_PATH.exists() and not args.force:
        raise ConfigError(f"{config.PRICES_PATH} already exists (use --force to overwrite)")
    state = seed_from_legacy_csv(Path(args.source))
    save_prices(state, config.PRICES_PATH)
    logger.info("seeded price state", extra={"units": len(state.units), "source": args.source})


def cmd_build(args: argparse.Namespace, summary: dict[str, Any]) -> None:
    today = _today()
    csv_path = config.CSV_DIR / csv_filename(today)
    summary.update(
        date=today.isoformat(),
        csv_path=str(csv_path.relative_to(config.ROOT)),
        csv_url=f"{config.PAGES_BASE_URL}/csv/{csv_path.name}",
    )
    builds = _load_json(BUILDS_PATH)
    if csv_path.exists() and not args.force:
        logger.info("today's file already built", extra={"file": csv_path.name})
        summary["built"] = False
    else:
        with _http() as client:
            units = scrape_units(client)
        warnings = price_inconsistencies(units)
        for warning in warnings:
            logger.warning("price inconsistency on website", extra={"detail": warning})
        state, changes = apply_prices(load_prices(config.PRICES_PATH), units, today)
        content = build_csv(units, state.units)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_path.write_bytes(content)
        save_prices(state, config.PRICES_PATH)
        offered = published_units(units)
        counts: dict[str, int] = {}
        for unit in offered:
            counts[unit.kind] = counts.get(unit.kind, 0) + 1
        previous = builds.get(today.isoformat(), {})
        builds[today.isoformat()] = {
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "counts": counts,
            "changes": previous.get("changes", []) + dump_changes(changes),
            "warnings": warnings,
        }
        _save_json(BUILDS_PATH, dict(sorted(builds.items())))
        summary["built"] = True
        logger.info(
            "built daily csv",
            extra={"file": csv_path.name, "rows": len(offered), "changes": len(changes)},
        )
    summary.update(builds.get(today.isoformat(), {}))
    xml = build_xml(published_days(config.CSV_DIR), today)
    config.XML_PATH.write_bytes(xml)
    config.MD5_PATH.write_text(md5_hex(xml), encoding="ascii")


def _utc_on(day: date, hour: int) -> datetime:
    return datetime.combine(day, dt_time(hour), tzinfo=timezone.utc)


def decide_delivery(
    *,
    force: bool,
    recorded: PublishedDay | None,
    harvester: bool,
    lookup: Callable[[], str | None],
    now_utc: datetime,
    today: date,
) -> tuple[str, str, str | None]:
    """(action, reason, resource id) for today: upload, record, wait or skip.

    `lookup` searches the admin panel for today's resource; it is only called
    when the answer depends on it, because it needs a browser login.
    Portal listings are never used: they lag new resources by many hours.
    """
    if force:
        return "upload", "forced by manual run", None
    if recorded is not None:
        return "skip", f"already recorded (resource {recorded.resource_id})", None
    if not harvester:
        return "upload", "browser delivery (harvester not active)", None
    if now_utc < _utc_on(today, config.HARVEST_READY_UTC_HOUR):
        return "wait", "before today's harvester import", None
    found = lookup()
    if found:
        return "record", "imported by the harvester", found
    if now_utc >= _utc_on(today, config.HARVEST_FALLBACK_UTC_HOUR):
        return "upload", "harvester missed today: fallback upload", None
    return "wait", "harvester import not visible yet", None


def cmd_plan(args: argparse.Namespace, summary: dict[str, Any]) -> None:
    recorded = load_published(config.PUBLISHED_PATH).days.get(_today())
    browser = args.force or recorded is None
    _github_output(browser="true" if browser else "false")
    logger.info("plan", extra={"browser": browser, "recorded": recorded is not None})


def cmd_deliver(args: argparse.Namespace, summary: dict[str, Any]) -> None:
    today = _today()
    title = resource_title(today)
    csv_path = config.CSV_DIR / csv_filename(today)
    mode = _delivery_mode()
    log = load_published(config.PUBLISHED_PATH)
    recorded = log.days.get(today)
    with ExitStack() as stack:
        pages: list[Page] = []

        def page() -> Page:
            if not pages:
                session = admin_session(
                    _env("DANE_GOV_EMAIL"), _env("DANE_GOV_PASSWORD"), headless=not args.headed
                )
                pages.append(stack.enter_context(session))
            return pages[0]

        harvester = mode == "harvester"
        if mode == "auto" and not args.force and recorded is None:
            with _http() as client:
                harvester = Portal(client).harvester_active(config.INSTITUTION_ID)
        action, reason, resource_id = decide_delivery(
            force=args.force,
            recorded=recorded,
            harvester=harvester and mode != "bot",
            lookup=lambda: find_resource_id(page(), title),
            now_utc=datetime.now(timezone.utc),
            today=today,
        )
        if action == "upload":
            resource_id = upload_csv(page(), csv_path, title)
    if action in ("upload", "record") and resource_id:
        # Recorded before verification so a retry slot never uploads the day again.
        log.days[today] = PublishedDay(
            resource_id=resource_id,
            uploaded_at=datetime.now(timezone.utc) if action == "upload" else None,
        )
        save_published(log, config.PUBLISHED_PATH)
    summary["deliver"] = {
        "action": action,
        "reason": reason,
        "mode": mode,
        "harvester": harvester,
        "resource_id": resource_id,
    }
    logger.info("delivery", extra={"action": action, "reason": reason, "resource": resource_id})


def _describe_difference(local: bytes, remote: bytes) -> str:
    local_lines = local.decode("utf-8", errors="replace").splitlines()
    remote_lines = remote.decode("utf-8", errors="replace").splitlines()
    if len(local_lines) != len(remote_lines):
        return (
            f"{len(remote_lines) - 1} rows on the portal vs {len(local_lines) - 1} in today's file"
        )
    for number, (mine, theirs) in enumerate(zip(local_lines, remote_lines), start=1):
        if mine != theirs:
            return f"first difference at line {number}"
    return "same text, different bytes (encoding or line endings)"


def _fetch_resource(portal: Portal, resource_id: str, wait_seconds: int) -> PortalResource:
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            return portal.resource(resource_id)
        except PortalError:
            if time.monotonic() >= deadline:
                raise
        time.sleep(15)


def cmd_verify(args: argparse.Namespace, summary: dict[str, Any]) -> None:
    today = _today()
    local = (config.CSV_DIR / csv_filename(today)).read_bytes()
    log = load_published(config.PUBLISHED_PATH)
    recorded = log.days.get(today)
    if recorded is None:
        if summary.get("deliver", {}).get("action") == "wait":
            summary["verify"] = {"status": "pending"}
            logger.info("waiting for the harvester to import today's file")
            return
        raise VerifyError(f"no dane.gov.pl resource recorded for {today.isoformat()}")
    uploaded_now = summary.get("deliver", {}).get("action") == "upload"
    with _http() as client:
        portal = Portal(client)
        resource = _fetch_resource(portal, recorded.resource_id, 180 if uploaded_now else 0)
        if not resource.title.endswith(today.isoformat()):
            raise VerifyError(f"resource {resource.id} is titled {resource.title!r}, not today's")
        remote = portal.download(resource.id)
    if remote != local:
        raise VerifyError(
            f"the file on dane.gov.pl ({resource.web_url}) is not today's file:"
            f" {_describe_difference(local, remote)}"
        )
    newly = recorded.verified_at is None
    if newly:
        log.days[today] = recorded.model_copy(
            update={"dataset_id": resource.dataset_id, "verified_at": datetime.now(timezone.utc)}
        )
        save_published(log, config.PUBLISHED_PATH)
    summary["verify"] = {
        "status": "ok",
        "resource_id": resource.id,
        "resource_url": resource.web_url,
        "newly_verified": newly,
    }
    logger.info("verified on dane.gov.pl", extra={"resource": resource.id, "new": newly})


def cmd_notify(args: argparse.Namespace, summary: dict[str, Any]) -> None:
    encoded = os.environ.get("SUMMARY_B64", "").strip()
    if encoded:
        summary.update(json.loads(base64.b64decode(encoded)))
    outcome = args.outcome
    failed_job = os.environ.get("FAILED_JOB", "").strip()
    if outcome == "failure" and "error" not in summary:
        step = {"pages": "publikacja plików (GitHub Pages)"}.get(
            failed_job, failed_job or "przebieg"
        )
        summary["error"] = {
            "step": step,
            "message": "zadanie zakończyło się błędem lub przekroczyło czas",
        }
    if outcome == "success" and not summary.get("verify", {}).get("newly_verified"):
        logger.info("nothing newly published in this run, no e-mail")
        return
    run_url = os.environ.get("RUN_URL", config.REPO_URL + "/actions")
    subject, text = compose(summary, outcome, run_url)
    if args.dry_run:
        print(subject, text, sep="\n\n")
        return
    recipients = [a.strip() for a in _env("NOTIFY_EMAILS").split(",") if a.strip()]
    send(_env("RESEND_API_KEY"), recipients, subject, text)


COMMANDS: dict[str, Callable[[argparse.Namespace, dict[str, Any]], None]] = {
    "seed-state": cmd_seed_state,
    "build": cmd_build,
    "plan": cmd_plan,
    "deliver": cmd_deliver,
    "verify": cmd_verify,
    "notify": cmd_notify,
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="danegov", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    seed = sub.add_parser("seed-state")
    seed.add_argument("--source", default="data.csv")
    seed.add_argument("--force", action="store_true")
    build = sub.add_parser("build")
    build.add_argument("--force", action="store_true", help="rebuild today's file")
    plan = sub.add_parser("plan")
    plan.add_argument("--force", action="store_true")
    deliver = sub.add_parser("deliver")
    deliver.add_argument("--force", action="store_true", help="upload even if already published")
    deliver.add_argument("--headed", action="store_true", help="show the browser")
    sub.add_parser("verify")
    notify = sub.add_parser("notify")
    notify.add_argument("--outcome", choices=("success", "failure"), required=True)
    notify.add_argument("--dry-run", action="store_true", help="print instead of sending")
    return parser


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    args = _parser().parse_args(argv)
    summary = _load_json(config.SUMMARY_PATH)
    try:
        COMMANDS[args.command](args, summary)
    except DaneGovError as exc:
        summary["error"] = {"step": args.command, "message": str(exc)}
        logger.error("step failed", extra={"step": args.command, "error": str(exc)})
        return 1
    except Exception as exc:
        summary["error"] = {"step": args.command, "message": f"{type(exc).__name__}: {exc}"}
        raise
    finally:
        if args.command != "notify":
            _save_json(config.SUMMARY_PATH, summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
