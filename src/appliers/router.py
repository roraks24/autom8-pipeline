import json
import logging
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from src.config import (
    ACTIVE_PLATFORMS,
    BASE_DIR,
    DB_PATH,
    ENFORCE_ACTIVE_PLATFORMS,
    LOGS_DIR,
    get_cookie_path,
    load_answer_bank,
)
from src.core.classifier import is_unpaid_role
from src.core.tailor import get_or_create_resume
from src.appliers.ats import fill_ashby_form, fill_greenhouse_form, fill_lever_form
from src.appliers.internshala import InternshalaApplier, fill_internshala_form
from src.appliers.wellfound import fill_wellfound_form

logger = logging.getLogger("router")


def apply_to_job(
    url: str,
    company: str = "Company",
    title: str = "GenAI Engineer",
    notes: str = "",
    submit: bool = False,
    headless: bool = False,
    use_chrome: bool = False,
    enforce_active: bool = True
) -> Tuple[str, Optional[Path]]:
    """
    Executes the full application flow for a single job across supported platforms.
    Routes to specialized engine (Wellfound v2.0, Internshala REST API, WWR, Naukri, or ATS).
    """
    # Enforce policy: apply only on wellfound and internshala
    if enforce_active and ENFORCE_ACTIVE_PLATFORMS:
        is_allowed = any(p in url.lower() for p in ACTIVE_PLATFORMS)
        if not is_allowed:
            print(f"\n[Policy Notice] Applying restricted to: {', '.join(p.capitalize() for p in ACTIVE_PLATFORMS)}. Skipping '{company}' ({url}).")
            return "skipped_policy", None

    # Enforce candidate policy: Strictly ZERO unpaid / volunteer roles
    if is_unpaid_role(text=notes, title=title):
        print(f"\n[Compensation Policy] Skipping '{company}' - '{title}': Unpaid / zero-stipend role excluded by candidate policy.")
        return "unpaid_excluded", None

    answers = load_answer_bank()
    resume_path = get_or_create_resume(company, title, notes)

    print("\n========================================================")
    print(f"Target: {company} - {title}")
    print(f"URL:    {url}")
    print(f"Mode:   {'[AUTO-SUBMIT]' if submit else '[PRE-FILL & STAGE FOR REVIEW]'}")
    print("========================================================")

    # 1. Route Internshala jobs directly via API applier (bypasses bot-detection and modals)
    if "internshala.com" in url:
        try:
            applier = InternshalaApplier()
            app_res = applier.apply_to_job(url, mode="submit" if submit else "stage")
            status = app_res["status"]
            print(f"  [Internshala API] Status: {status.upper()} - {app_res.get('message', '')}")
            return status, None
        except Exception as e:
            logger.warning(f"Internshala API applier failed ({e}). Falling back to browser automation...")

    clean_comp = re.sub(r"[^a-zA-Z0-9_-]", "_", company)
    original_url = url
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    screenshot_path = LOGS_DIR / f"{clean_comp}_{timestamp}.png"

    with sync_playwright() as p:
        is_portal = ("wellfound.com" in url or "internshala.com" in url or use_chrome)
        profile_dir = Path.home() / ".chrome_job_profile"
        browser = None
        context = None

        # Normalize Greenhouse URLs if they point to corporate wrappers
        if "gh_jid=" in url:
            m = re.search(r"gh_jid=(\d+)", url)
            if m:
                token = m.group(1)
                comp_slug = clean_comp.lower()
                url = f"https://boards.greenhouse.io/embed/job_app?for={comp_slug}&token={token}"

        if is_portal:
            UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            try:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    channel="chrome",
                    headless=headless,
                    user_agent=UA,
                    args=["--disable-blink-features=AutomationControlled"],
                    ignore_default_args=["--enable-automation"],
                    viewport={"width": 1280, "height": 900}
                )
            except Exception:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    headless=headless,
                    user_agent=UA,
                    args=["--disable-blink-features=AutomationControlled"],
                    ignore_default_args=["--enable-automation"],
                    viewport={"width": 1280, "height": 900}
                )
            for platform_name in ACTIVE_PLATFORMS:
                cp = get_cookie_path(platform_name)
                if cp.exists():
                    try:
                        with open(cp, "r", encoding="utf-8") as f:
                            context.add_cookies(json.load(f))
                    except Exception:
                        pass
            page = context.pages[0] if context.pages else context.new_page()
        else:
            try:
                browser = p.chromium.launch(channel="chrome", headless=headless)
            except Exception:
                browser = p.chromium.launch(headless=headless)
            page = browser.new_page(viewport={"width": 1280, "height": 900})

        status = "staged_for_review"
        try:
            print(f"  Navigating to application page: {url}...")
            for attempt in range(3):
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    break
                except Exception as ne:
                    ne_str = str(ne).lower()
                    if attempt < 2 and any(k in ne_str for k in ["timeout", "timed_out", "err_connection", "err_name_not_resolved", "net::"]):
                        print(f"  ! Network delay navigating to {url[:50]}... Retrying in 5s (Attempt {attempt+1}/3)...")
                        time.sleep(5)
                    else:
                        raise ne

            page.wait_for_timeout(2000)

            # Route to appropriate platform handler
            parsed_domain = urlparse(url).netloc.lower()

            if "internshala.com" in parsed_domain:
                print("  [Platform] Detected Internshala Portal")
                inter_status = fill_internshala_form(page, answers, resume_path)
                if inter_status == "login_required":
                    status = "login_required"
            elif "wellfound.com" in parsed_domain:
                print("  [Platform] Detected Wellfound Portal (Pipeline v2.0)")
                wf_status = fill_wellfound_form(page, answers, resume_path, job_title=title, company=company, submit=submit)
                status = wf_status
            elif "ashbyhq.com" in parsed_domain or "jobs.ashbyhq.com" in parsed_domain or page.query_selector("form#ashby-application-form, [data-ashby-app]"):
                print("  [Platform] Detected Ashby Form")
                res = fill_ashby_form(page, answers, resume_path)
                if res == "dropped_demographics_required":
                    status = "dropped_demographics_required"
            elif "lever.co" in parsed_domain or page.query_selector("form#application-form[action*='lever']"):
                print("  [Platform] Detected Lever Form")
                res = fill_lever_form(page, answers, resume_path)
                if res == "dropped_demographics_required":
                    status = "dropped_demographics_required"
            elif "greenhouse.io" in parsed_domain or page.query_selector("#apply_app, #application_form, form[action*='greenhouse']"):
                print("  [Platform] Detected Greenhouse Form")
                res = fill_greenhouse_form(page, answers, resume_path)
                if res == "dropped_demographics_required":
                    status = "dropped_demographics_required"
            else:
                print("  [Platform] Generic / Custom Form - filling standard selectors...")
                res = fill_ashby_form(page, answers, resume_path)
                if res == "dropped_demographics_required":
                    status = "dropped_demographics_required"

            page.wait_for_timeout(1000)
            try:
                page.screenshot(path=str(screenshot_path), timeout=5000)
                print(f"  [Screenshot] Staged application captured: {screenshot_path.name}")
            except Exception as se:
                print(f"  ! Screenshot warning: {se}")

            if status == "dropped_demographics_required":
                print("  [Policy Drop] Form requires mandatory demographics / marks screening. Skipped per candidate instruction.")
                return "dropped_demographics_required", screenshot_path

            if status in ["already_applied", "expired", "ineligible"]:
                print(f"  [Status] Wellfound job resolution: {status.upper()}")
                return status, screenshot_path

            if status not in ["login_required", "applied", "already_applied", "expired", "ineligible"]:
                if submit:
                    submit_btn = page.query_selector('button:has-text("Submit Application"), button:has-text("Send Application"), button:has-text("Submit"), input[type="submit"]')
                    if submit_btn:
                        is_disabled = submit_btn.evaluate("el => el.disabled || el.getAttribute('aria-disabled') === 'true'")
                        if is_disabled:
                            print("  ! Submit button is currently disabled. Checking constraints...")
                            page_text = page.inner_text("body").lower()
                            if "not accepting applications from your current location" in page_text or "relocation constraints" in page_text or ("does not offer visa sponsorship" in page_text and "your profile indicates you require sponsorship" in page_text):
                                print("  ! Ineligible: Location/visa constraint detected (candidate outside hiring region). Marked ineligible.")
                                status = "ineligible"
                                return "ineligible", screenshot_path
                            else:
                                page.wait_for_timeout(1500)
                                if submit_btn.evaluate("el => el.disabled || el.getAttribute('aria-disabled') === 'true'"):
                                    print("  ! Required fields pending employer confirmation. Kept staged for review.")
                                    status = "staged_for_review"
                                else:
                                    print("  [Action] Clicking Submit button...")
                                    submit_btn.click(timeout=10000)
                                    page.wait_for_timeout(4000)
                                    post_screenshot = LOGS_DIR / f"{clean_comp}_{timestamp}_submitted.png"
                                    page.screenshot(path=str(post_screenshot))
                                    print(f"  [Success] Submission complete! Proof: {post_screenshot.name}")
                                    status = "applied"
                        else:
                            print("  [Action] Clicking Submit button...")
                            try:
                                submit_btn.click(timeout=10000)
                                page.wait_for_timeout(4000)
                                post_screenshot = LOGS_DIR / f"{clean_comp}_{timestamp}_submitted.png"
                                page.screenshot(path=str(post_screenshot))
                                print(f"  [Success] Submission complete! Proof: {post_screenshot.name}")
                                status = "applied"
                            except Exception as click_err:
                                print(f"  ! Submit click warning: {click_err}. Kept staged.")
                                status = "staged_for_review"
                    else:
                        print("  ! Submit button not found automatically. Kept staged.")
                        status = "staged_for_review"
                else:
                    print("  [Ready] Form is pre-filled with your answers and tailored resume.")
                    status = "staged_for_review"

        except Exception as e:
            print(f"  ! Error during application flow: {e}")
            status = "failed"
        finally:
            if context:
                try: context.close()
                except Exception: pass
            if browser:
                try: browser.close()
                except Exception: pass

    # Update jobs.db
    if DB_PATH.exists():
        try:
            con = sqlite3.connect(DB_PATH)
            con.execute(
                "UPDATE jobs SET status=?, notes=notes || ? WHERE url=? OR url=?",
                (status, f"; App status: {status}", original_url, url)
            )
            con.commit()
            con.close()
        except Exception:
            pass

    return status, screenshot_path
