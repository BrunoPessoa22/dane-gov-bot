"""Command line entry points used by the GitHub Actions workflow.

    python -m danegov build          scrape the website, write today's CSV + XML + MD5
    python -m danegov plan-upload    decide whether the browser bot must upload today
    python -m danegov upload         upload today's CSV through the admin panel
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
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from danegov import config
from danegov.build import build_csv, csv_filename, published_units, resource_title
from danegov.harvester import build_xml, md5_hex, published_days
from danegov.logs import setup_logging
from danegov.models import DaneGovError
from danegov.notify import compose, send
from danegov.portal import Portal
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
from danegov.upload import upload_csv

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


def cmd_plan_upload(args: argparse.Namespace, summary: dict[str, Any]) -> None:
    today = _today()
    mode = _delivery_mode()
    now_utc = datetime.now(timezone.utc)
    with _http() as client:
        portal = Portal(client)
        existing = portal.resources_for_day(config.INSTITUTION_ID, today)
        harvester = portal.harvester_active(config.INSTITUTION_ID) if mode == "auto" else None
    if args.force:
        upload, reason = True, "forced by manual run"
    elif existing:
        upload, reason = False, f"already on dane.gov.pl (resource {existing[0].id})"
    elif mode == "harvester":
        upload, reason = False, "harvester mode"
    elif mode == "bot":
        upload, reason = True, "bot mode"
    elif not harvester:
        upload, reason = True, "harvester not active yet"
    elif now_utc.hour >= config.HARVEST_FALLBACK_UTC_HOUR:
        upload, reason = True, "harvester active but today's resource missing: fallback upload"
    else:
        upload, reason = False, "harvester active, waiting for the daily import"
    summary["upload"] = {"planned": upload, "reason": reason, "mode": mode, "harvester": harvester}
    logger.info("upload plan", extra={"upload": upload, "reason": reason, "mode": mode})
    _github_output(upload="true" if upload else "false")


def cmd_upload(args: argparse.Namespace, summary: dict[str, Any]) -> None:
    today = _today()
    csv_path = config.CSV_DIR / csv_filename(today)
    upload_csv(
        csv_path,
        resource_title(today),
        email=_env("DANE_GOV_EMAIL"),
        password=_env("DANE_GOV_PASSWORD"),
        headless=not args.headed,
    )
    summary.setdefault("upload", {})["done"] = True


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


def cmd_verify(args: argparse.Namespace, summary: dict[str, Any]) -> None:
    today = _today()
    local = (config.CSV_DIR / csv_filename(today)).read_bytes()
    uploaded_now = bool(summary.get("upload", {}).get("done"))
    deadline = time.monotonic() + (180 if uploaded_now else 0)
    with _http() as client:
        portal = Portal(client)
        while True:
            resources = portal.resources_for_day(config.INSTITUTION_ID, today)
            if resources or time.monotonic() >= deadline:
                break
            time.sleep(15)
        if not resources:
            waiting_for_harvest = not summary.get("upload", {}).get("planned", False) and (
                datetime.now(timezone.utc).hour < config.HARVEST_DEADLINE_UTC_HOUR
            )
            if waiting_for_harvest:
                summary["verify"] = {"status": "pending"}
                logger.info("waiting for the harvester to import today's file")
                return
            raise VerifyError(f"dane.gov.pl has no resource for {today.isoformat()}")
        latest = resources[0]
        remote = portal.download(latest.id)
    if remote != local:
        raise VerifyError(
            f"the file on dane.gov.pl ({latest.web_url}) is not today's file:"
            f" {_describe_difference(local, remote)}"
        )
    log = load_published(config.PUBLISHED_PATH)
    previous = log.days.get(today)
    newly = previous is None or previous.resource_id != latest.id
    if newly:
        log.days[today] = PublishedDay(
            resource_id=latest.id,
            dataset_id=latest.dataset_id,
            verified_at=datetime.now(timezone.utc),
        )
        save_published(log, config.PUBLISHED_PATH)
    summary["verify"] = {
        "status": "ok",
        "resource_id": latest.id,
        "resource_url": latest.web_url,
        "newly_verified": newly,
    }
    logger.info("verified on dane.gov.pl", extra={"resource": latest.id, "new": newly})


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
    "plan-upload": cmd_plan_upload,
    "upload": cmd_upload,
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
    plan = sub.add_parser("plan-upload")
    plan.add_argument("--force", action="store_true", help="upload even if already published")
    upload = sub.add_parser("upload")
    upload.add_argument("--headed", action="store_true", help="show the browser")
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
