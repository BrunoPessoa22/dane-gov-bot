#!/usr/bin/env python3
"""
Dane.gov.pl Automated CSV Uploader
Uploads CSV file to the Polish government data portal daily.
"""

import os
import sys
import time
import glob
from datetime import datetime
import logging

from playwright.sync_api import sync_playwright

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Credentials from environment
EMAIL = os.getenv('DANE_GOV_EMAIL')
PASSWORD = os.getenv('DANE_GOV_PASSWORD')


def find_csv_file() -> str:
    """Find the CSV file in the current directory."""
    csv_files = glob.glob('*.csv')
    if not csv_files:
        raise FileNotFoundError("No CSV file found in directory")
    return csv_files[0]


def upload_to_dane_gov(csv_path: str) -> bool:
    """Upload CSV to dane.gov.pl"""

    today = datetime.now().strftime("%Y-%m-%d")
    title = f"Ceny ofertowe mieszkan dewelopera Trend Inwestycje {today}"

    logger.info(f"CSV file: {csv_path}")
    logger.info(f"Title: {title}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1920, 'height': 1080})
        page.set_default_timeout(60000)

        try:
            # Step 1: Login
            logger.info("Step 1: Logging in...")
            page.goto("https://dane.gov.pl/pl/user/login")
            time.sleep(5)  # Wait for JS to load

            # Close cookie dialog
            try:
                page.locator('button:has-text("Zamknij okno dialogowe")').first.click(timeout=5000)
                time.sleep(2)
            except:
                pass

            # Click "Wybierz" link for email login (second link)
            wybierz_links = page.locator('a:has-text("Wybierz")').all()
            if len(wybierz_links) >= 2:
                wybierz_links[1].click()  # Second link = email login
                logger.info("Selected email login method")
            time.sleep(3)

            # Fill email
            page.fill('input[name="email"]', EMAIL)
            time.sleep(1)

            # Fill password
            page.fill('input[name="password"]', PASSWORD)
            time.sleep(1)

            # Click login button
            page.click('button[type="submit"]')
            time.sleep(5)
            logger.info("Login successful")

            # Step 2: Go to Admin Panel
            logger.info("Step 2: Navigating to admin panel...")
            try:
                page.click('a:has-text("Panel administratora")', timeout=5000)
            except:
                page.goto("https://admin.dane.gov.pl/")
            page.wait_for_load_state("networkidle")
            time.sleep(2)

            # Step 3: Go to Resources
            logger.info("Step 3: Navigating to resources...")
            try:
                page.click('a:has-text("Zasoby")', timeout=5000)
            except:
                page.goto("https://admin.dane.gov.pl/resources/resource/")
            page.wait_for_load_state("networkidle")
            time.sleep(2)

            # Step 4: Click on latest resource
            logger.info("Step 4: Opening latest resource...")
            page.wait_for_selector('table')
            links = page.locator('a[href*="/resources/resource/"][href*="/change"]').all()
            if links:
                links[0].click()
            else:
                page.click('table tbody tr:first-child a')
            page.wait_for_load_state("networkidle")
            time.sleep(2)

            # Step 5: Copy to new resource
            logger.info("Step 5: Creating copy for new resource...")
            page.click('a:has-text("Kopiuj do nowego")')
            page.wait_for_load_state("networkidle")
            time.sleep(2)

            # Step 6: Upload file
            logger.info("Step 6: Uploading CSV file...")
            file_input = page.locator('input[type="file"][name="file"]')
            file_input.set_input_files(csv_path)
            time.sleep(2)

            # Step 7: Update title
            logger.info("Step 7: Updating title...")
            title_input = page.locator('input[name="title"], #id_title').first
            title_input.clear()
            title_input.fill(title)
            time.sleep(1)

            # Step 8: Configure Znaki umowne
            logger.info("Step 8: Configuring 'Znaki umowne'...")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
            time.sleep(1)

            try:
                iks_option = page.locator('select[id*="from"] option:has-text("X (IKS)")')
                if iks_option.count() > 0:
                    select = page.locator('select[id*="from"]').filter(has=iks_option)
                    select.select_option(label="X (IKS) - wypelnienie pozycji jest niemozliwe lub niecelowe")
                page.click('a.selector-add, .selector-chooser a:first-child')
            except Exception as e:
                logger.warning(f"Could not configure Znaki umowne: {e}")

            time.sleep(1)

            # Step 9: Save
            logger.info("Step 9: Saving...")
            page.evaluate("window.scrollTo(0, 0)")
            time.sleep(1)
            page.click('input[name="_save"], input[value="Zapisz"]')
            page.wait_for_load_state("networkidle")
            time.sleep(3)

            logger.info("Upload completed successfully!")
            return True

        except Exception as e:
            logger.error(f"Upload failed: {e}")
            # Take screenshot on error
            page.screenshot(path="error.png")
            # Log page content for debugging
            logger.error(f"Page URL: {page.url}")
            logger.error(f"Page title: {page.title()}")
            return False

        finally:
            browser.close()


def main():
    logger.info("=" * 50)
    logger.info(f"Dane.gov.pl Upload - {datetime.now()}")
    logger.info("=" * 50)

    if not EMAIL or not PASSWORD:
        logger.error("Missing DANE_GOV_EMAIL or DANE_GOV_PASSWORD")
        sys.exit(1)

    csv_path = find_csv_file()
    success = upload_to_dane_gov(csv_path)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
