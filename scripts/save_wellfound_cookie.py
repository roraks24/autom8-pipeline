#!/usr/bin/env python3
"""
save_wellfound_cookie.py - Imports a Wellfound cookie string or session token into ~/.chrome_job_profile
"""
import sys
import json
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

def parse_cookie_header(cookie_str, domain=".wellfound.com"):
    cookies = []
    # format: name=value; name2=value2
    parts = cookie_str.strip().split(";")
    for part in parts:
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, val = part.split("=", 1)
        name = name.strip()
        val = val.strip()
        cookies.append({
            "name": name,
            "value": val,
            "domain": domain,
            "path": "/",
            "secure": True,
            "sameSite": "Lax"
        })
    return cookies

def import_and_verify(cookie_str):
    cookies = parse_cookie_header(cookie_str)
    if not cookies:
        print("❌ No valid cookies parsed.")
        return False
        
    print(f"Parsed {len(cookies)} cookies. Injecting into ~/.chrome_job_profile...")
    profile_dir = Path.home() / ".chrome_job_profile"
    
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
            viewport={"width": 1280, "height": 900}
        )
        ctx.add_cookies(cookies)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        print("Navigating to https://wellfound.com/jobs to verify authentication...")
        page.goto("https://wellfound.com/jobs", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        
        url = page.url.lower()
        title = page.title()
        has_login_btn = page.query_selector('header button:has-text("Log In"), header a:has-text("Log In")')
        page.screenshot(path="application_logs/wellfound_auth_test.png")
        
        if not has_login_btn:
            print("✅ [SUCCESS] Fully authenticated into Wellfound! Session active and saved.")
            success = True
        else:
            print(f"⚠️ Warning: Still saw Log In button. Check application_logs/wellfound_auth_test.png")
            success = False
            
        ctx.close()
        return success

if __name__ == "__main__":
    if len(sys.argv) > 1:
        raw = " ".join(sys.argv[1:])
        import_and_verify(raw)
    else:
        print("Usage: python save_wellfound_cookie.py '<cookie_string>'")
