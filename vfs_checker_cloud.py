#!/usr/bin/env python3
"""
VFS Global Italy Appointment Checker - Cloud / GitHub Actions version
Checks for available slots at the LONDON centre specifically.
Runs once, emails if found, then exits.
Credentials are read from environment variables (GitHub Secrets).
"""

import os
import sys
import time
import smtplib
import logging
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException, TimeoutException

VFS_EMAIL          = os.environ.get("VFS_EMAIL", "")
VFS_PASSWORD       = os.environ.get("VFS_PASSWORD", "")
GMAIL_ADDRESS      = os.environ.get("GMAIL_ADDRESS", "trintruf@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

VFS_URL         = "https://visa.vfsglobal.com/gbr/en/ita/book-an-appointment"
TARGET_CENTRE   = "London"   # The visa application centre to check

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)


# ── Email ──────────────────────────────────────────────────────────────────

def send_email(subject, body):
    if not GMAIL_APP_PASSWORD:
        log.error("GMAIL_APP_PASSWORD not set.")
        return False
    try:
        msg = MIMEMultipart()
        msg["From"] = GMAIL_ADDRESS
        msg["To"]   = GMAIL_ADDRESS
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.send_message(msg)
        log.info(f"Email sent to {GMAIL_ADDRESS}")
        return True
    except smtplib.SMTPAuthenticationError:
        log.error("Email auth failed. Use a Gmail App Password.")
        return False
    except Exception as e:
        log.error(f"Email failed: {e}")
        return False


# ── Browser ────────────────────────────────────────────────────────────────

def create_headless_browser():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    try:
        driver = webdriver.Chrome(options=options)
    except Exception:
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


# ── Login ──────────────────────────────────────────────────────────────────

def is_login_page(driver):
    url = driver.current_url.lower()
    return any(x in url for x in ["sign-in", "login", "signin", "auth", "accounts"])


def attempt_login(driver):
    if not VFS_EMAIL or not VFS_PASSWORD:
        log.error("VFS credentials not set.")
        return False
    try:
        email_el = None
        for sel in ["input[type='email']", "input[name='email']", "input[id*='mail']"]:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            if els and els[0].is_displayed():
                email_el = els[0]
                break
        if not email_el:
            log.warning("Email field not found.")
            return False
        email_el.clear()
        email_el.send_keys(VFS_EMAIL)

        pwd_els = driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
        if not pwd_els:
            log.warning("Password field not found.")
            return False
        pwd_els[0].clear()
        pwd_els[0].send_keys(VFS_PASSWORD)

        submit = driver.find_elements(By.CSS_SELECTOR, "button[type='submit']")
        if submit:
            submit[0].click()
        else:
            from selenium.webdriver.common.keys import Keys
            pwd_els[0].send_keys(Keys.RETURN)

        time.sleep(5)
        log.info("Login submitted.")
        return True
    except Exception as e:
        log.error(f"Login error: {e}")
        return False


def dismiss_cookies(driver):
    for sel in ["button[id*='accept']", "button[class*='accept']", "button[id*='cookie']"]:
        try:
            for btn in driver.find_elements(By.CSS_SELECTOR, sel):
                if btn.is_displayed():
                    btn.click()
                    time.sleep(0.5)
                    return
        except Exception:
            pass


# ── London centre selection ────────────────────────────────────────────────

def select_london_centre(driver):
    """
    After login, the VFS booking page asks you to choose a visa
    application centre. This function finds that dropdown (or radio
    button list) and selects the London option.
    Returns True if London was selected, False otherwise.
    """
    wait = WebDriverWait(driver, 15)
    centre_keyword = TARGET_CENTRE.lower()

    # 1) Try a <select> dropdown first
    try:
        selects = driver.find_elements(By.TAG_NAME, "select")
        for sel_el in selects:
            opts = sel_el.find_elements(By.TAG_NAME, "option")
            for opt in opts:
                if centre_keyword in opt.text.lower():
                    Select(sel_el).select_by_visible_text(opt.text)
                    log.info(f"Selected centre via dropdown: {opt.text}")
                    time.sleep(2)
                    return True
    except Exception as e:
        log.debug(f"Dropdown centre select failed: {e}")

    # 2) Try clickable cards / buttons / radio buttons labelled with the city
    try:
        # Look for any clickable element whose text contains "London"
        candidates = driver.find_elements(
            By.XPATH,
            f"//*[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
            f"'abcdefghijklmnopqrstuvwxyz'),'{centre_keyword}') "
            f"and (self::button or self::label or self::a or self::div or self::li)]"
        )
        for el in candidates:
            if el.is_displayed() and el.is_enabled():
                el.click()
                log.info(f"Clicked centre option: {el.text.strip()}")
                time.sleep(2)
                return True
    except Exception as e:
        log.debug(f"Clickable centre select failed: {e}")

    # 3) Try radio inputs near a label that says London
    try:
        labels = driver.find_elements(By.TAG_NAME, "label")
        for label in labels:
            if centre_keyword in label.text.lower():
                label.click()
                log.info(f"Clicked label: {label.text.strip()}")
                time.sleep(2)
                return True
    except Exception as e:
        log.debug(f"Radio label select failed: {e}")

    log.warning(
        f"Could not find a '{TARGET_CENTRE}' centre selector on this page. "
        "The page may require more interaction first, or the layout has changed."
    )
    return False


# ── Appointment detection ──────────────────────────────────────────────────

def check_for_slots(driver):
    """
    Scan the current page for available appointment slots.
    Returns (found: bool, description: str)
    """
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text.lower()

        no_slot_phrases = [
            "no appointment slots",
            "no appointments available",
            "no slots available",
            "currently no appointments",
            "no available appointment",
            "slots are not available",
            "appointment not available",
            "no dates available",
            "there are no available",
        ]
        for phrase in no_slot_phrases:
            if phrase in body_text:
                log.info(f'No slots - "{phrase}" detected')
                return False, ""

        # Active calendar cells
        active_dates = []
        for sel in [
            "td.available", "td.enabled",
            ".day:not(.disabled):not(.old):not(.new)",
            "td[class*='available']",
            "button.calendar-day:not([disabled])",
            ".slot-item:not(.disabled)",
            "[data-available='true']",
        ]:
            try:
                for cell in driver.find_elements(By.CSS_SELECTOR, sel):
                    text = cell.text.strip()
                    if text and cell.is_displayed():
                        active_dates.append(text)
            except Exception:
                pass

        if active_dates:
            return True, f"Available dates at {TARGET_CENTRE}: {', '.join(active_dates[:10])}"

        # Time-slot dropdowns
        try:
            for sel_el in driver.find_elements(By.TAG_NAME, "select"):
                opts = [
                    o for o in sel_el.find_elements(By.TAG_NAME, "option")
                    if o.get_attribute("value")
                ]
                if opts:
                    times = [o.text.strip() for o in opts[:5]]
                    return True, f"Time slots at {TARGET_CENTRE}: {', '.join(times)}"
        except Exception:
            pass

        # Active Book/Select/Confirm button
        try:
            btns = driver.find_elements(
                By.XPATH,
                "//button[not(@disabled) and ("
                "contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'book') or "
                "contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'select') or "
                "contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'confirm')"
                ")]"
            )
            visible = [b for b in btns if b.is_displayed()]
            if visible:
                return True, f"{len(visible)} booking button(s) active at {TARGET_CENTRE}"
        except Exception:
            pass

        log.info("No clear signal either way.")
        return False, ""

    except Exception as e:
        log.error(f"Error scanning page: {e}")
        return False, ""


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 55)
    log.info(f"VFS Italy Checker - {TARGET_CENTRE} centre (cloud run)")
    log.info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    log.info("=" * 55)

    driver = None
    slots_found = False

    try:
        driver = create_headless_browser()

        # Load booking page
        log.info(f"Loading: {VFS_URL}")
        driver.get(VFS_URL)
        time.sleep(6)

        # Login if needed
        if is_login_page(driver):
            log.info("Login page detected. Attempting auto-login...")
            if not attempt_login(driver):
                log.error("Login failed. Check VFS_EMAIL and VFS_PASSWORD secrets.")
                sys.exit(1)
            time.sleep(5)

        # Navigate to booking page
        if "book-an-appointment" not in driver.current_url:
            log.info("Navigating to booking page...")
            driver.get(VFS_URL)
            time.sleep(5)

        dismiss_cookies(driver)

        # Select London centre
        log.info(f"Selecting {TARGET_CENTRE} centre...")
        centre_selected = select_london_centre(driver)
        if centre_selected:
            time.sleep(3)  # Let the page update after selecting
        else:
            log.warning("Proceeding without centre selection — checking all available slots.")

        # Scan for slots
        log.info("Scanning for appointment slots...")
        slots_found, description = check_for_slots(driver)

        if slots_found:
            log.info(f"*** SLOTS FOUND: {description} ***")
            subject = f"VFS {TARGET_CENTRE} APPOINTMENT AVAILABLE - Book NOW!"
            body = (
                f"Italy Schengen visa appointment slots detected at {TARGET_CENTRE}!\n\n"
                f"Details: {description}\n\n"
                f"Book immediately at:\n{VFS_URL}\n\n"
                f"Detected: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
                f"-- VFS Checker (GitHub Actions)"
            )
            send_email(subject, body)
        else:
            log.info(f"No slots available at {TARGET_CENTRE} this check.")

    except WebDriverException as e:
        log.error(f"Browser error: {e}")
        sys.exit(1)
    except Exception as e:
        log.error(f"Unexpected error: {e}")
        sys.exit(1)
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    log.info("Check complete.")
    sys.exit(0 if not slots_found else 2)


if __name__ == "__main__":
    main()
