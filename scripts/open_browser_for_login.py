import time
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

profile_dir = Path.home() / ".chrome_job_profile"

print(f"Opening browser window for Internshala login at {profile_dir}...", flush=True)

with sync_playwright() as p:
    try:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            channel="chrome",
            headless=False,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
            viewport=None
        )
    except Exception:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
            viewport=None
        )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://internshala.com/login/student")
    print("\n" + "="*60, flush=True)
    print(">>> BROWSER WINDOW IS OPEN <<<", flush=True)
    print("Please log in to your Internshala student account in the browser.", flush=True)
    print("="*60 + "\n", flush=True)

    # Monitor until logged in or closed
    try:
        while len(ctx.pages) > 0 and not page.is_closed():
            url = page.url.lower()
            if "dashboard" in url or "student/dashboard" in url or "my_applications" in url:
                print("\n[SUCCESS] Login detected! Internshala session is active.", flush=True)
                print("Saving profile...", flush=True)
                time.sleep(3)
                break
            time.sleep(1)
    except Exception as e:
        print(f"Notice: {e}", flush=True)
    finally:
        try:
            ctx.close()
        except Exception:
            pass

print("Done! Browser session saved successfully.", flush=True)
