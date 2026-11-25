import json
from pathlib import Path
from typing import Iterable, Optional

from src.config import ACTIVE_PLATFORMS, CHROME_PROFILE_DIR, get_cookie_path

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


def launch_persistent_context(
    playwright,
    user_data_dir: Optional[Path] = None,
    headless: bool = True,
    viewport: Optional[dict] = None,
    load_cookies_for: Optional[Iterable[str]] = None,
):
    """
    Launches a persistent Playwright Chromium context with anti-detection flags.
    Prefers installed Google Chrome channel and gracefully falls back to bundled Chromium.
    """
    profile = Path(user_data_dir) if user_data_dir else CHROME_PROFILE_DIR
    vp = viewport or {"width": 1280, "height": 900}
    common_kwargs = {
        "user_data_dir": str(profile),
        "headless": headless,
        "user_agent": DEFAULT_USER_AGENT,
        "args": ["--disable-blink-features=AutomationControlled"],
        "ignore_default_args": ["--enable-automation"],
        "viewport": vp,
    }

    try:
        context = playwright.chromium.launch_persistent_context(channel="chrome", **common_kwargs)
    except Exception:
        context = playwright.chromium.launch_persistent_context(**common_kwargs)

    for platform_name in load_cookies_for or []:
        cp = get_cookie_path(platform_name)
        if cp.exists():
            try:
                cookies = json.loads(cp.read_text(encoding="utf-8"))
                context.add_cookies(cookies)
            except Exception:
                pass

    return context


def launch_ephemeral_browser(playwright, headless: bool = True):
    """Launches a non-persistent Chromium browser for standalone ATS forms."""
    try:
        return playwright.chromium.launch(channel="chrome", headless=headless)
    except Exception:
        return playwright.chromium.launch(headless=headless)


def open_interactive_login(platform: str) -> None:
    """Opens a visible Chrome browser window for manual one-time session login."""
    import time
    from playwright.sync_api import sync_playwright

    login_urls = {
        "wellfound": "https://wellfound.com/login",
        "internshala": "https://internshala.com/login/student",
    }
    p_clean = platform.lower().strip()
    if p_clean not in login_urls:
        raise ValueError(f"Unsupported interactive login platform: {platform}")

    target_url = login_urls[p_clean]
    print(f"\nOpening Chrome to log into {p_clean.capitalize()}...")
    print(f"URL: {target_url}")
    print("Complete login in the browser window, then close the window to save the session.\n")

    with sync_playwright() as p:
        ctx = launch_persistent_context(
            p,
            user_data_dir=CHROME_PROFILE_DIR,
            headless=False,
            load_cookies_for=ACTIVE_PLATFORMS,
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(target_url)
        try:
            while len(ctx.pages) > 0 and not page.is_closed():
                time.sleep(1)
        except (KeyboardInterrupt, Exception):
            pass
        finally:
            try:
                ctx.close()
            except Exception:
                pass

    print(f"\nSession saved to {CHROME_PROFILE_DIR}!")
