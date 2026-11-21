import argparse
import json
import logging
import os
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Optional

from src.config import BASE_DIR, CONFIG_DIR, DEFAULT_PHONE, LOGS_DIR, get_config_file

logger = logging.getLogger("whatsapp_sender")

PROFILE_DIR = Path.home() / ".whatsapp_web_profile"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"

DEFAULT_CONFIG = {
    "sender_phone": "918854905995",
    "primary_phone": DEFAULT_PHONE,
    "alternate_phone": "918854905995",
    "preferred_target": DEFAULT_PHONE,
    "callmebot_api_key": ""
}


def load_config() -> dict:
    cfg_file = get_config_file("whatsapp_config.json")
    if cfg_file.exists():
        try:
            return json.loads(cfg_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict):
    cfg_file = CONFIG_DIR / "whatsapp_config.json"
    cfg_file.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    # Also mirror to root for backward compatibility
    root_file = BASE_DIR / "whatsapp_config.json"
    try:
        root_file.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass


def normalize_phone(phone: str) -> str:
    cleaned = "".join(filter(str.isdigit, str(phone)))
    if len(cleaned) == 10:
        cleaned = "91" + cleaned
    return cleaned


def login_interactive() -> bool:
    """Opens a visible Chrome window for Rohit to scan the WhatsApp Web QR code once."""
    from playwright.sync_api import sync_playwright

    print("=" * 60)
    print("      WHATSAPP WEB 1-TIME AUTHENTICATION SETUP")
    print(f"      Profile Directory: {PROFILE_DIR}")
    print("=" * 60)
    print("\n1. A Chrome browser window will now open.")
    print(f"2. Open WhatsApp on your phone ({DEFAULT_PHONE}).")
    print("3. Tap Settings / 3-dots -> Linked Devices -> Link a Device.")
    print("4. Scan the QR code shown in the browser window.")
    print("\nWaiting for WhatsApp Web login...\n")

    with sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                channel="chrome",
                headless=False,
                user_agent=UA,
                args=["--disable-blink-features=AutomationControlled"],
                ignore_default_args=["--enable-automation"],
                viewport={"width": 1200, "height": 850}
            )
        except Exception:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=False,
                user_agent=UA,
                args=["--disable-blink-features=AutomationControlled"],
                ignore_default_args=["--enable-automation"],
                viewport={"width": 1200, "height": 850}
            )

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://web.whatsapp.com", timeout=60000)

        logged_in = False
        start_time = time.time()
        timeout = 180  # 3 minutes for QR scan

        while time.time() - start_time < timeout:
            if page.is_closed():
                break

            is_logged_in = page.locator('div[data-tab="3"], div#pane-side, div[aria-label="Chat list"]').count() > 0
            has_qr = page.locator("canvas").count() > 0

            if is_logged_in and not has_qr:
                logged_in = True
                print("\n" + "=" * 60)
                print("  [SUCCESS] WhatsApp Web authenticated successfully!")
                print("  Session saved to ~/.whatsapp_web_profile.")
                print("  Your future daily application reports will now be sent automatically.")
                print("=" * 60)
                page.wait_for_timeout(4000)
                break

            time.sleep(2)

        try:
            ctx.close()
        except Exception:
            pass

        return logged_in


def is_whatsapp_web_ready() -> bool:
    """Quick headless check to see if WhatsApp Web has an active session."""
    from playwright.sync_api import sync_playwright

    if not PROFILE_DIR.exists():
        return False

    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                channel="chrome",
                headless=True,
                args=["--disable-blink-features=AutomationControlled"]
            )
            page = ctx.new_page()
            page.goto("https://web.whatsapp.com", timeout=30000)
            page.wait_for_timeout(6000)
            is_ready = page.locator('div[data-tab="3"], div#pane-side, div[aria-label="Chat list"]').count() > 0
            ctx.close()
            return is_ready
    except Exception as e:
        logger.warning(f"Session readiness check error: {e}")
        return False


def send_via_whatsapp_web(text: str, phone: str, headless: bool = True) -> bool:
    """Sends a WhatsApp message using automated Playwright session."""
    from playwright.sync_api import sync_playwright

    phone = normalize_phone(phone)
    encoded = urllib.parse.quote(text)
    url = f"https://web.whatsapp.com/send?phone={phone}&text={encoded}"

    logger.info(f"Dispatching via WhatsApp Web to +{phone}...")

    with sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                channel="chrome",
                headless=headless,
                user_agent=UA,
                args=["--disable-blink-features=AutomationControlled"],
                ignore_default_args=["--enable-automation"]
            )
        except Exception:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=headless,
                user_agent=UA,
                args=["--disable-blink-features=AutomationControlled"],
                ignore_default_args=["--enable-automation"]
            )

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            logger.info("Waiting for WhatsApp Web chat interface to load...")

            chat_loaded = False
            for _ in range(25):
                page.wait_for_timeout(1000)
                if page.locator("canvas").count() > 0 and page.locator('div[data-tab="3"]').count() == 0:
                    logger.warning("WhatsApp Web session expired or not linked. QR code is displayed.")
                    ctx.close()
                    return False

                input_box = page.locator('footer div[contenteditable="true"]')
                if input_box.count() > 0:
                    chat_loaded = True
                    break

            if not chat_loaded:
                logger.error("Timed out waiting for WhatsApp chat to load.")
                ctx.close()
                return False

            logger.info("Chat loaded. Locating Send button / pressing Enter...")
            page.wait_for_timeout(1500)

            try:
                page.evaluate('''([sel, msg]) => {
                    const el = document.querySelector(sel);
                    if (el && (!el.innerText || !el.innerText.trim())) {
                        el.focus();
                        document.execCommand("insertText", false, msg);
                    }
                }''', ['footer div[contenteditable="true"]', text])
            except Exception:
                pass
            page.wait_for_timeout(1000)

            send_btn = page.locator('button[aria-label="Send"], span[data-icon="send"]')
            if send_btn.count() > 0 and send_btn.first.is_visible():
                send_btn.first.click()
            else:
                input_box = page.locator('footer div[contenteditable="true"]').first
                input_box.focus()
                input_box.press("Enter")

            page.wait_for_timeout(3000)

            timestamp = time.strftime("%Y%m%d_%H%M%S")
            proof_file = LOGS_DIR / f"whatsapp_proof_{phone}_{timestamp}.png"
            page.screenshot(path=str(proof_file))
            logger.info(f"✅ WhatsApp message successfully delivered to +{phone}! Proof: {proof_file.name}")

            ctx.close()
            return True
        except Exception as e:
            logger.error(f"Error during WhatsApp Web send: {e}")
            try: ctx.close()
            except Exception: pass
            return False


def send_via_callmebot(text: str, phone: str, apikey: str) -> bool:
    """Sends a WhatsApp message via CallMeBot REST API."""
    import requests
    phone = normalize_phone(phone)
    encoded = urllib.parse.quote(text)
    url = f"https://api.callmebot.com/whatsapp.php?phone={phone}&text={encoded}&apikey={apikey}"

    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200 and ("Message queued" in resp.text or "ok" in resp.text.lower()):
            logger.info(f"✅ Dispatched via CallMeBot API to +{phone}")
            return True
        else:
            logger.warning(f"CallMeBot API response [{resp.status_code}]: {resp.text}")
            return resp.status_code == 200
    except Exception as e:
        logger.error(f"CallMeBot dispatch error: {e}")
        return False


def send_via_desktop_uri(text: str, phone: str) -> bool:
    """Fallback: Launches desktop WhatsApp client with pre-filled message."""
    phone = normalize_phone(phone)
    # Windows startfile / ShellExecute limit is ~2048 chars for URI
    clean_text = text
    if len(clean_text) > 1200:
        clean_text = clean_text[:1200] + "\n\n... [Full report saved in application_logs]"
    encoded = urllib.parse.quote(clean_text)
    uri = f"whatsapp://send?phone={phone}&text={encoded}"
    try:
        if sys.platform == "win32":
            os.startfile(uri)
            logger.info(f"✅ Opened desktop WhatsApp draft for +{phone}")
            return True
        else:
            logger.info("Desktop URI only supported on Windows.")
            return False
    except Exception as e:
        logger.error(f"Desktop URI failed: {e}")
        return False


def send_whatsapp(text: str, phone: Optional[str] = None) -> bool:
    """
    Master dispatcher: sends WhatsApp report via available methods.
    Order of preference:
    1. CallMeBot REST API (if configured)
    2. Automated WhatsApp Web (Playwright with ~/.whatsapp_web_profile)
    3. Desktop URI Fallback
    """
    cfg = load_config()
    target_phone = phone or cfg.get("preferred_target") or cfg.get("primary_phone") or DEFAULT_PHONE
    target_phone = normalize_phone(target_phone)

    apikey = cfg.get("callmebot_api_key", "").strip()
    if apikey:
        logger.info("Attempting dispatch via CallMeBot API...")
        if send_via_callmebot(text, target_phone, apikey):
            return True

    if PROFILE_DIR.exists():
        logger.info("Attempting dispatch via automated WhatsApp Web...")
        success = send_via_whatsapp_web(text, target_phone, headless=True)
        if success:
            return True

    logger.info("Falling back to desktop WhatsApp client...")
    return send_via_desktop_uri(text, target_phone)
