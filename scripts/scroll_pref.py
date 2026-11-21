import json
from pathlib import Path
from playwright.sync_api import sync_playwright

profile_dir = Path.home() / ".chrome_job_profile"
cookie_path = Path("cookies/wellfound_cookies.json")

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        headless=True,
        viewport={"width": 1280, "height": 900}
    )
    if cookie_path.exists():
        with open(cookie_path, "r", encoding="utf-8") as f:
            context.add_cookies(json.load(f))
            
    page = context.pages[0] if context.pages else context.new_page()
    page.goto("https://wellfound.com/profile/edit/preferences", wait_until="domcontentloaded", timeout=25000)
    page.wait_for_timeout(3000)
    
    page.evaluate("window.scrollBy(0, 800)")
    page.wait_for_timeout(1000)
    page.screenshot(path="application_logs/wf_preferences_scroll1.png")
    
    page.evaluate("window.scrollBy(0, 800)")
    page.wait_for_timeout(1000)
    page.screenshot(path="application_logs/wf_preferences_scroll2.png")
    
    context.close()
