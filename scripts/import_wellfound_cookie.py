# Raw cookie string from user
raw_cookie = """_iidt=ljpBBEjUdXSYsp9QKMzU3XWIZgk0aGnLF3gHZNgtID+aGpJ83QMD94cQBpEsTq3pHL7I2LocjE0vVz592e01Qwc85Ty4/uTO/dYKb6Q=; _vid_t=+IXk9FVqBDKZeK32i8KLfiSaHVxwdukHjWuEAqt13SJ9ZZcT2jcgLlm/J3RR9SsokHBbaOVwLrt5+vHW9ZnMIW853vT2MVACBHMhtiY=; wellfound_default_consent=1|implied-full; rl_anonymous_id=%221470fa34-22ca-4bf2-8997-267565b141a0%22; rl_page_init_referrer=%22%24direct%22; ajs_anonymous_id=1470fa34-22ca-4bf2-8997-267565b141a0; _wellfound=7b54e65da869fa8b071dab7476d7073c.i; rl_user_id=%2220814975%22; cf_clearance=6SmlpoHHDzKonCCKE5.TkL3JvDeCDWx.pFfg1igKP1I-1791094563-1.2.1.1-6T0WHfRJNSRWI2LLzO6SB5qUdmjGRRjU.y_PqVMelVkpj4S757YOTMYXOYXuVmI5bRZJFKKDFnrHsfJ2wel5rVpdIbjY.MfM7NNMP_zRSc9GVnJjHCTW_lrwFTyqgGQpgNxfJ9VoYEKbD3n2h4r6tGfym.l5uRrtCSUkyS.LuLkPxd3AhWmRsiHx.Mo_roYWOjYGYOJO.Yl_tT62o5SGQC5i_Biw3xSkdoh2VKaZj9pYqS5CK7MI6Gzl9ABJhbr9hjoiWFm8Gg21KMXxmqMMhSOqTJEHlZmBLTIUqu1aX84x1XqXP_8s1wIyM_LwP8ne7aCZOkdw1njDMwQS19wNSl_.Zw5V.HSP9lH8LkuTz9Y; TAsessionID=2a2d8abb-7ced-433b-81f1-6bf203a05c81|NEW; notice_behavior=implied|as; rl_trait=%7B%22name%22%3A%22Rohit%20Saini%22%2C%22first_name%22%3A%22Rohit%22%2C%22last_name%22%3A%22Saini%22%2C%22email%22%3A%22rsaini2407%40gmail.com%22%2C%22email_status%22%3A%22active%22%2C%22profile_url%22%3A%22https%3A%2F%2Fwellfound.com%2Frohit-saini-78%22%2C%22created_at%22%3A%222026-03-19T03%3A22%3A20.000%2B00%3A00%22%2C%22is_recruiter%22%3Afalse%2C%22is_candidate%22%3Atrue%2C%22is_candidate_success%22%3Atrue%2C%22is_admin%22%3Afalse%2C%22is_banned%22%3Afalse%2C%22candidate_primary_role%22%3A%22Machine%20Learning%20Engineer%22%2C%22years_experience_in_primary_role%22%3A0%2C%22job_search_status%22%3A%22interviewing%22%2C%22primary_location%22%3A%22Jaipur%22%2C%22primary_location_country%22%3A%22India%22%2C%22candidate_location_tags%22%3A%5B%22Jaipur%22%5D%2C%22candidate_interested_locations%22%3A%5B%22Mumbai%22%2C%22Noida%22%2C%22Bangalore%20Urban%22%5D%2C%22candidate_role_tags%22%3A%5B%22Data%20Engineer%22%2C%22Backend%20Engineer%22%2C%22Machine%20Learning%20Engineer%22%5D%2C%22candidate_remote_work_preference%22%3Atrue%2C%22candidate_desired_salary%22%3A1000%2C%22candidate_desired_salary_currency%22%3A%22USD%22%2C%22candidate_last_active_at%22%3A%222026-09-08T06%3A07%3A29.000%2B00%3A00%22%2C%22candidate_quality%22%3A%22quality_candidate%22%2C%22alist_previously_invited%22%3Afalse%2C%22last_login_at%22%3A%222026-07-28T13%3A14%3A31.000%2B00%3A00%22%2C%22eligible_for_al_elite%22%3Afalse%7D; rl_session=%7B%22id%22%3A1791094564194%2C%22expiresAt%22%3A1791096366261%2C%22timeout%22%3A1800000%2C%22autoTrack%22%3Atrue%2C%22sessionStart%22%3Afalse%7D"""

import json
from pathlib import Path
from playwright.sync_api import sync_playwright

def parse_cookies(cookie_str, domain=".wellfound.com"):
    cookies = []
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
            "sameSite": "None" if name in ["cf_clearance", "_wellfound"] else "Lax"
        })
    return cookies

cookies = parse_cookies(raw_cookie)
with open("wellfound_cookies.json", "w", encoding="utf-8") as f:
    json.dump(cookies, f, indent=2)

print(f"Saved {len(cookies)} cookies to wellfound_cookies.json")

profile_dir = Path.home() / ".chrome_job_profile"
print(f"Injecting into persistent profile at {profile_dir}...")

with sync_playwright() as p:
    try:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            channel="chrome",
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
            viewport={"width": 1280, "height": 900}
        )
    except Exception:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
            viewport={"width": 1280, "height": 900}
        )
    
    ctx.add_cookies(cookies)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    print("Navigating to https://wellfound.com/jobs...")
    page.goto("https://wellfound.com/jobs", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(4000)
    
    print(f"Current URL: {page.url}")
    print(f"Page Title: {page.title()}")
    
    # Check if logged in
    login_btn = page.query_selector('header button:has-text("Log In"), header a:has-text("Log In")')
    avatar = page.query_selector('[data-test*="avatar"], img[alt*="Rohit"], [aria-label*="Profile"], [aria-label*="account"], [data-test*="user"]')
    body_text = page.inner_text("body")
    
    page.screenshot(path="application_logs/wellfound_logged_in_verification.png")
    print("Screenshot saved to application_logs/wellfound_logged_in_verification.png")
    
    if "Rohit" in body_text or not login_btn or avatar:
        print("[SUCCESS] Rohit Saini is fully logged into Wellfound!")
    else:
        print("Notice: Check verification screenshot for login state.")
        
    ctx.close()
