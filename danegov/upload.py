"""Browser upload to the dane.gov.pl admin panel (the original bot's flow).

Used until the XML harvester is active, and as its fallback afterwards. It
copies the newest resource ("Kopiuj do nowego") so all metadata carries over,
then swaps in the day's file and title.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from danegov.models import DaneGovError

logger = logging.getLogger(__name__)

LOGIN_URL = "https://dane.gov.pl/pl/user/login"
ADMIN_URL = "https://admin.dane.gov.pl/"
RESOURCES_URL = "https://admin.dane.gov.pl/resources/resource/"


class UploadError(DaneGovError):
    pass


def _login(page: Page, email: str, password: str) -> None:
    page.goto(LOGIN_URL)
    time.sleep(5)  # the login page renders its form with JS
    try:
        page.locator('button:has-text("Zamknij okno dialogowe")').first.click(timeout=5000)
        time.sleep(2)
    except PlaywrightTimeoutError:
        logger.info("no cookie dialog")
    choose_links = page.locator('a:has-text("Wybierz")').all()
    if len(choose_links) >= 2:
        choose_links[1].click()  # second method = e-mail and password
        time.sleep(3)
    page.fill('input[name="email"]', email)
    page.fill('input[name="password"]', password)
    page.click('button[type="submit"]')
    time.sleep(5)
    if page.locator('input[name="password"]').count() and "login" in page.url:
        raise UploadError("login to dane.gov.pl failed (still on the login form)")


def _open_admin_resources(page: Page) -> None:
    try:
        page.click('a:has-text("Panel administratora")', timeout=5000)
    except PlaywrightTimeoutError:
        page.goto(ADMIN_URL)
    page.wait_for_load_state("networkidle")
    try:
        page.click('a:has-text("Zasoby")', timeout=5000)
    except PlaywrightTimeoutError:
        page.goto(RESOURCES_URL)
    page.wait_for_load_state("networkidle")
    if "admin.dane.gov.pl" not in page.url:
        raise UploadError(f"did not reach the admin panel (at {page.url})")


def _copy_latest_resource(page: Page) -> None:
    page.wait_for_selector("table")
    links = page.locator('a[href*="/resources/resource/"][href*="/change"]').all()
    if links:
        links[0].click()
    else:
        page.click("table tbody tr:first-child a")
    page.wait_for_load_state("networkidle")
    page.click('a:has-text("Kopiuj do nowego")')
    page.wait_for_load_state("networkidle")
    time.sleep(2)


def _fill_form(page: Page, csv_path: Path, title: str) -> None:
    page.locator('input[type="file"][name="file"]').set_input_files(str(csv_path))
    time.sleep(2)
    title_input = page.locator('input[name="title"], #id_title').first
    title_input.clear()
    title_input.fill(title)
    # "Znaki umowne": move "X (Iks)" to the selected list. Copied resources
    # usually carry it over already, so a missing option is not an error.
    try:
        page.locator('option:has-text("X (Iks)")').first.click(timeout=5000)
        page.locator("a.selector-add, a[title*='Wybierz'], .selector-chooser a").first.click(
            timeout=5000
        )
    except PlaywrightTimeoutError:
        logger.info("special sign X already selected or not offered")


def _save(page: Page) -> None:
    page.evaluate("window.scrollTo(0, 0)")
    page.locator(
        'input[name="_save"], input[value="Zapisz"], button:has-text("Zapisz"), input[type="submit"]'
    ).first.click()
    page.wait_for_load_state("networkidle")
    time.sleep(3)
    errors = page.locator(".errornote, .errorlist")
    if errors.count():
        raise UploadError(f"admin rejected the form: {errors.first.inner_text().strip()}")


def _new_resource_id(page: Page, title: str) -> str:
    """Id of the newest resource with this title (the admin list is newest first)."""
    page.goto(RESOURCES_URL)
    page.wait_for_load_state("networkidle")
    for link in page.locator('a[href*="/resources/resource/"][href*="/change"]').all()[:10]:
        if link.inner_text().strip() == title:
            match = re.search(r"/resources/resource/(\d+)/change", link.get_attribute("href") or "")
            if match:
                return match.group(1)
    raise UploadError(f"saved, but no resource titled {title!r} in the admin list")


def upload_csv(csv_path: Path, title: str, email: str, password: str, headless: bool = True) -> str:
    """Upload the file as a new resource and return its id."""
    if not csv_path.exists():
        raise UploadError(f"CSV not found: {csv_path}")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.set_default_timeout(60000)
        step = "login"
        try:
            _login(page, email, password)
            step = "open admin resources"
            _open_admin_resources(page)
            step = "copy latest resource"
            _copy_latest_resource(page)
            step = "fill form"
            _fill_form(page, csv_path, title)
            step = "save"
            _save(page)
            step = "find new resource"
            resource_id = _new_resource_id(page, title)
        except PlaywrightError as exc:
            raise UploadError(f"browser step '{step}' failed at {page.url}: {exc}") from exc
        finally:
            browser.close()
    logger.info("uploaded", extra={"file": csv_path.name, "title": title, "resource": resource_id})
    return resource_id
