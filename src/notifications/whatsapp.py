import argparse
import json
import logging
import os
import sys
import time
import urllib.parse
from typing import Optional

from src.config import CONFIG_DIR, DEFAULT_PHONE, WHATSAPP_CONFIG_PATH, WHATSAPP_PROFILE_DIR
from src.core.browser import launch_persistent_context

logger = logging.getLogger("whatsapp_sender")

DEFAULT_CONFIG = {
    "sender_phone": "918854905995",
    "primary_phone": DEFAULT_PHONE,
    "alternate_phone": "918854905995",
    "preferred_target": DEFAULT_PHONE,
    "callmebot_api_key": "",
}


def load_config() -> dict:
    if WHATSAPP_CONFIG_PATH.exists():
        try:
            return json.loads(WHATSAPP_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict) -> None:
    CONFIG_DIR.mkdir(exist_ok=True)
    WHATSAPP_CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def normalize_phone(phone: str) -> str:
    cleaned = "".join(filter(str.isdigit, str(phone)))
    if len(cleaned) == 10:
        cleaned = "91" + cleaned
    return cleaned


def login_interactive() -> bool:
    """Opens a visible Chrome window to scan the WhatsApp Web QR code once."""
    from playwright.sync_api import sync_playwright

    print("=" * 60)
    print("      WHATSAPP WEB 1-TIME AUTHENTICATION SETUP")
    print(f"      Profile Directory: {WHATSAPP_PROFILE_DIR}")
    print("=" * 60)
    print(f"\n1. Scan the QR code from WhatsApp on +{DEFAULT_PHONE} (Linked Devices).")

    with sync_playwright() as p:
        ctx = launch_persistent_context(
            p,
            user_data_dir=WHATSAPP_PROFILE_DIR,
            headless=False,
            viewport={"width": 1200, "height": 850},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://web.whatsapp.com", timeout=60000)

        logged_in = False
        start_time = time.time()
        while time.time() - start_time < 180:
            if page.is_closed():
                break
            is_logged_in = page.locator('div[data-tab="3"], div#pane-side, div[aria-label="Chat list"]').count() > 0
            has_qr = page.locator("canvas").count() > 0
            if is_logged_in and not has_qr:
                logged_in = True
                print("\n[SUCCESS] WhatsApp Web authenticated! Session saved.")
                page.wait_for_timeout(3000)
                break
            time.sleep(2)

        try:
            ctx.close()
        except Exception:
            pass
        return logged_in


def send_via_whatsapp_web(text: str, phone: str, headless: bool = True) -> bool:
    """Sends a WhatsApp message using automated Playwright session (no screenshots saved)."""
    from playwright.sync_api import sync_playwright

    phone = normalize_phone(phone)
    encoded = urllib.parse.quote(text)
    url = f"https://web.whatsapp.com/send?phone={phone}&text={encoded}"
    logger.info(f"Dispatching via WhatsApp Web to +{phone}...")

    with sync_playwright() as p:
        ctx = launch_persistent_context(p, user_data_dir=WHATSAPP_PROFILE_DIR, headless=headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            chat_loaded = False
            for _ in range(25):
                page.wait_for_timeout(1000)
                if page.locator("canvas").count() > 0 and page.locator('div[data-tab="3"]').count() == 0:
                    logger.warning("WhatsApp Web session expired or not linked (QR code displayed).")
                    ctx.close()
                    return False
                if page.locator('footer div[contenteditable="true"]').count() > 0:
                    chat_loaded = True
                    break

            if not chat_loaded:
                logger.error("Timed out waiting for WhatsApp chat interface.")
                ctx.close()
                return False

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
            page.wait_for_timeout(800)

            send_btn = page.locator('button[aria-label="Send"], span[data-icon="send"]')
            if send_btn.count() > 0 and send_btn.first.is_visible():
                send_btn.first.click()
            else:
                input_box = page.locator('footer div[contenteditable="true"]').first
                input_box.focus()
                input_box.press("Enter")

            page.wait_for_timeout(2500)
            logger.info(f"✅ WhatsApp message delivered to +{phone}.")
            ctx.close()
            return True
        except Exception as e:
            logger.error(f"Error during WhatsApp Web send: {e}")
            try:
                ctx.close()
            except Exception:
                pass
            return False


def send_via_callmebot(text: str, phone: str, apikey: str) -> bool:
    import requests
    phone = normalize_phone(phone)
    encoded = urllib.parse.quote(text)
    url = f"https://api.callmebot.com/whatsapp.php?phone={phone}&text={encoded}&apikey={apikey}"
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200 and ("Message queued" in resp.text or "ok" in resp.text.lower()):
            logger.info(f"✅ Dispatched via CallMeBot API to +{phone}")
            return True
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"CallMeBot dispatch error: {e}")
        return False


def send_via_desktop_uri(text: str, phone: str) -> bool:
    """Fallback: Launches desktop WhatsApp client with pre-filled summary."""
    phone = normalize_phone(phone)
    clean_text = text[:1200] + "\n\n... [Full log saved in data/applied_jobs.json]" if len(text) > 1200 else text
    uri = f"whatsapp://send?phone={phone}&text={urllib.parse.quote(clean_text)}"
    try:
        if sys.platform == "win32":
            os.startfile(uri)
            logger.info(f"✅ Opened desktop WhatsApp draft for +{phone}")
            return True
        return False
    except Exception as e:
        logger.error(f"Desktop URI failed: {e}")
        return False


def send_whatsapp(text: str, phone: Optional[str] = None) -> bool:
    """Master dispatcher: CallMeBot -> WhatsApp Web -> Desktop URI."""
    cfg = load_config()
    target_phone = normalize_phone(phone or cfg.get("preferred_target") or cfg.get("primary_phone") or DEFAULT_PHONE)

    apikey = cfg.get("callmebot_api_key", "").strip()
    if apikey and send_via_callmebot(text, target_phone, apikey):
        return True

    if WHATSAPP_PROFILE_DIR.exists() and send_via_whatsapp_web(text, target_phone, headless=True):
        return True

    logger.info("Falling back to desktop WhatsApp client...")
    return send_via_desktop_uri(text, target_phone)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WhatsApp notification helper")
    parser.add_argument("--login", action="store_true", help="Authenticate WhatsApp Web QR")
    parser.add_argument("--phone", type=str, default=None)
    parser.add_argument("--message", type=str, default="Test notification from Autom8 Pipeline")
    args = parser.parse_args()
    if args.login:
        login_interactive()
    else:
        send_whatsapp(args.message, phone=args.phone)
