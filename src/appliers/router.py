import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from src.appliers.ats import fill_ashby_form, fill_greenhouse_form, fill_lever_form
from src.appliers.internshala import InternshalaApplier, fill_internshala_form
from src.appliers.wellfound import fill_wellfound_form
from src.config import (
    ACTIVE_PLATFORMS,
    CHROME_PROFILE_DIR,
    ENFORCE_ACTIVE_PLATFORMS,
    load_answer_bank,
)
from src.core.browser import launch_ephemeral_browser, launch_persistent_context
from src.core.classifier import classify_role, is_excluded_company, is_unpaid_role
from src.core.tailor import get_or_create_resume
from src.storage.applied_store import AppliedJobsStore, SkippedCacheStore

logger = logging.getLogger("router")

SKIP_STATUSES = {
    "unpaid_excluded",
    "ineligible",
    "expired",
    "already_applied",
    "rejected",
    "dropped_demographics_required",
    "non_target_role",
}


def _detect_source(url: str) -> str:
    u = url.lower()
    if "internshala.com" in u:
        return "internshala"
    if "wellfound.com" in u:
        return "wellfound"
    if "greenhouse.io" in u:
        return "greenhouse"
    if "lever.co" in u:
        return "lever"
    if "ashbyhq.com" in u:
        return "ashby"
    return "external"


def _persist_outcome(
    status: str,
    url: str,
    company: str,
    title: str,
    location: str,
    notes: str,
    salary: Optional[str],
    skills: Optional[str],
    job_id: str,
    target_tier: Optional[int],
    target_category: Optional[str],
    tailored_resume: Optional[str],
    application_id: Optional[str],
    reason: str,
    applied_store: AppliedJobsStore,
    skipped_store: SkippedCacheStore,
) -> None:
    """Persists terminal outcomes into the single Applied JSON DB or Skip-Cache."""
    source = _detect_source(url)
    if not target_tier:
        tier_val, cat_val, _ = classify_role(title, notes, url=url, source=source)
        target_tier = tier_val or 2
        target_category = target_category or cat_val or "AI Engineer / Developer"

    if status == "applied":
        applied_store.record_applied({
            "id": job_id,
            "source": source,
            "company": company,
            "title": title,
            "location": location,
            "url": url,
            "application_id": application_id,
            "salary": salary,
            "target_tier": target_tier,
            "target_category": target_category,
            "skills": skills,
            "tailored_resume": Path(tailored_resume).name if tailored_resume else None,
            "notes": notes,
        })
    elif status in SKIP_STATUSES:
        skipped_store.record_skipped(
            url=url,
            job_id=job_id,
            source=source,
            company=company,
            title=title,
            status=status,
            reason=reason or notes or status,
        )


def apply_to_job(
    url: str,
    company: str = "Company",
    title: str = "GenAI Engineer",
    notes: str = "",
    salary: str = "",
    skills: str = "",
    location: str = "Remote / India",
    job_id: str = "",
    target_tier: Optional[int] = None,
    target_category: Optional[str] = None,
    submit: bool = True,
    headless: bool = True,
    use_chrome: bool = False,
    enforce_active: bool = True,
    applied_store: Optional[AppliedJobsStore] = None,
    skipped_store: Optional[SkippedCacheStore] = None,
) -> Dict[str, Any]:
    """
    Executes end-to-end application flow for a single job across supported platforms
    without storing any screenshots or SQLite records.
    """
    applied_db = applied_store or AppliedJobsStore()
    skipped_db = skipped_store or SkippedCacheStore()

    if enforce_active and ENFORCE_ACTIVE_PLATFORMS:
        if not any(p in url.lower() for p in ACTIVE_PLATFORMS):
            print(f"\n[Policy Notice] Applying restricted to: {', '.join(p.capitalize() for p in ACTIVE_PLATFORMS)}. Skipping '{company}'.")
            return {"status": "skipped_policy", "company": company, "title": title, "url": url}

    if applied_db.has_applied(url=url, job_id=job_id, company=company, title=title):
        print(f"\n[Dedup Notice] Already recorded in applied_jobs.json: '{company}' - '{title}'.")
        return {"status": "already_applied", "company": company, "title": title, "url": url}

    if is_excluded_company(company):
        print(f"\n[Excluded Policy] Skipping '{company}': listed in config/excluded.txt.")
        _persist_outcome(
            "rejected", url, company, title, location, notes, salary, skills,
            job_id, target_tier, target_category, None, None, "Company listed in config/excluded.txt",
            applied_db, skipped_db,
        )
        return {"status": "rejected", "company": company, "title": title, "url": url}

    if is_unpaid_role(text=notes, title=title, salary=salary):
        print(f"\n[Compensation Policy] Skipping '{company}' - '{title}': Unpaid role excluded.")
        _persist_outcome(
            "unpaid_excluded", url, company, title, location, notes, salary, skills,
            job_id, target_tier, target_category, None, None, "Unpaid role excluded by policy",
            applied_db, skipped_db,
        )
        return {"status": "unpaid_excluded", "company": company, "title": title, "url": url}

    print("\n========================================================")
    print(f"Target: {company} - {title}")
    print(f"URL:    {url}")
    print(f"Mode:   {'[AUTO-SUBMIT]' if submit else '[PRE-FILL & STAGE FOR REVIEW]'}")
    print("========================================================")

    # 1. Internshala REST API route (bypasses bot detection and handles tailoring internally)
    if "internshala.com" in url.lower():
        try:
            applier = InternshalaApplier()
            app_res = applier.apply_to_job(url, mode="submit" if submit else "stage")
            status = app_res["status"]
            comp_resolved = app_res.get("company") or company
            title_resolved = app_res.get("title") or title
            sal_resolved = app_res.get("salary") or salary
            sk_list = app_res.get("skills_required") or []
            skills_resolved = ", ".join(sk_list[:6]) if sk_list else skills
            app_id = app_res.get("application_id")
            res_pdf = app_res.get("tailored_resume")
            msg = app_res.get("message", "")

            print(f"  [Internshala API] Status: {status.upper()} - {msg}")
            _persist_outcome(
                status, url, comp_resolved, title_resolved, location,
                f"Application ID: {app_id}" if app_id else (msg or notes),
                sal_resolved, skills_resolved, job_id, target_tier, target_category,
                res_pdf, str(app_id) if app_id else None, msg, applied_db, skipped_db,
            )
            return {
                "status": status,
                "company": comp_resolved,
                "title": title_resolved,
                "url": url,
                "application_id": app_id,
                "salary": sal_resolved,
                "skills": skills_resolved,
                "tailored_resume": res_pdf,
                "message": msg,
            }
        except Exception as e:
            logger.warning(f"Internshala API applier failed ({e}). Falling back to browser automation...")

    # 2. Browser automation route (Wellfound / ATS)
    # Defer Wellfound PDF resume creation until live JD is scraped inside fill_wellfound_form
    answers = load_answer_bank()
    is_wellfound_url = "wellfound.com" in url.lower()
    resume_path: Optional[Path] = None if is_wellfound_url else get_or_create_resume(company, title, notes)
    wf_meta: Dict[str, Any] = {}
    original_url = url
    clean_comp = re.sub(r"[^a-zA-Z0-9_-]", "_", company)

    if "gh_jid=" in url:
        m = re.search(r"gh_jid=(\d+)", url)
        if m:
            url = f"https://boards.greenhouse.io/embed/job_app?for={clean_comp.lower()}&token={m.group(1)}"

    is_portal = ("wellfound.com" in url or "internshala.com" in url or use_chrome)
    status = "staged_for_review"

    with sync_playwright() as p:
        context = None
        browser = None
        if is_portal:
            context = launch_persistent_context(
                p,
                user_data_dir=CHROME_PROFILE_DIR,
                headless=headless,
                load_cookies_for=ACTIVE_PLATFORMS,
            )
            page = context.pages[0] if context.pages else context.new_page()
        else:
            browser = launch_ephemeral_browser(p, headless=headless)
            page = browser.new_page(viewport={"width": 1280, "height": 900})

        try:
            print(f"  Navigating to application page: {url}...")
            for attempt in range(3):
                try:
                    page.goto(url, wait_until="commit", timeout=30000)
                    page.wait_for_timeout(2500)
                    break
                except Exception as ne:
                    ne_str = str(ne).lower()
                    if attempt < 2 and any(k in ne_str for k in ("timeout", "timed_out", "err_connection", "err_name_not_resolved", "net::")):
                        print(f"  ! Network delay navigating to {url[:50]}... Retrying in 5s ({attempt+1}/3)...")
                        time.sleep(5)
                    else:
                        raise

            page.wait_for_timeout(2000)
            parsed_domain = urlparse(url).netloc.lower()

            if "internshala.com" in parsed_domain:
                print("  [Platform] Detected Internshala Portal")
                if fill_internshala_form(page, answers, resume_path) == "login_required":
                    status = "login_required"
            elif "wellfound.com" in parsed_domain:
                print("  [Platform] Detected Wellfound Portal")
                status = fill_wellfound_form(
                    page,
                    answers,
                    resume_path=None,
                    job_title=title,
                    company=company,
                    submit=submit,
                    salary=salary,
                    jd_text=notes,
                    out_meta=wf_meta,
                )
                if wf_meta.get("tailored_resume"):
                    resume_path = Path(wf_meta["tailored_resume"])
                if wf_meta.get("salary"):
                    salary = wf_meta["salary"]
            elif "ashbyhq.com" in parsed_domain or page.query_selector("form#ashby-application-form, [data-ashby-app]"):
                print("  [Platform] Detected Ashby Form")
                if resume_path is None:
                    resume_path = get_or_create_resume(company, title, notes)
                if fill_ashby_form(page, answers, resume_path) == "dropped_demographics_required":
                    status = "dropped_demographics_required"
            elif "lever.co" in parsed_domain or page.query_selector("form#application-form[action*='lever']"):
                print("  [Platform] Detected Lever Form")
                if resume_path is None:
                    resume_path = get_or_create_resume(company, title, notes)
                if fill_lever_form(page, answers, resume_path) == "dropped_demographics_required":
                    status = "dropped_demographics_required"
            elif "greenhouse.io" in parsed_domain or page.query_selector("#apply_app, #application_form, form[action*='greenhouse']"):
                print("  [Platform] Detected Greenhouse Form")
                if resume_path is None:
                    resume_path = get_or_create_resume(company, title, notes)
                if fill_greenhouse_form(page, answers, resume_path) == "dropped_demographics_required":
                    status = "dropped_demographics_required"
            else:
                print("  [Platform] Generic Form - filling standard selectors...")
                if resume_path is None:
                    resume_path = get_or_create_resume(company, title, notes)
                if fill_ashby_form(page, answers, resume_path) == "dropped_demographics_required":
                    status = "dropped_demographics_required"

            if status not in ("login_required", "applied", "already_applied", "expired", "ineligible", "unpaid_excluded", "dropped_demographics_required"):
                if submit:
                    submit_btn = page.query_selector('button:has-text("Submit Application"), button:has-text("Send Application"), button:has-text("Submit"), input[type="submit"]')
                    if submit_btn:
                        is_disabled = submit_btn.evaluate("el => el.disabled || el.getAttribute('aria-disabled') === 'true'")
                        if is_disabled:
                            page_text = page.inner_text("body").lower()
                            if (
                                "not accepting applications from your current location" in page_text
                                or "relocation constraints" in page_text
                                or ("does not offer visa sponsorship" in page_text and "your profile indicates you require sponsorship" in page_text)
                            ):
                                status = "ineligible"
                            else:
                                page.wait_for_timeout(1500)
                                if submit_btn.evaluate("el => el.disabled || el.getAttribute('aria-disabled') === 'true'"):
                                    status = "staged_for_review"
                                else:
                                    submit_btn.click(timeout=10000)
                                    page.wait_for_timeout(3500)
                                    status = "applied"
                        else:
                            try:
                                submit_btn.click(timeout=10000)
                                page.wait_for_timeout(3500)
                                status = "applied"
                            except Exception as click_err:
                                print(f"  ! Submit click warning: {click_err}. Kept staged.")
                                status = "staged_for_review"
                    else:
                        print("  ! Submit button not found automatically. Kept staged.")
                        status = "staged_for_review"
                else:
                    status = "staged_for_review"
        except Exception as e:
            print(f"  ! Error during application flow: {e}")
            status = "failed"
        finally:
            if context:
                try:
                    context.close()
                except Exception:
                    pass
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass

    tailored_str = str(resume_path) if resume_path else None
    _persist_outcome(
        status, original_url, company, title, location, notes, salary or None, skills or None,
        job_id, target_tier, target_category, tailored_str, None, status,
        applied_db, skipped_db,
    )

    return {
        "status": status,
        "company": company,
        "title": title,
        "url": original_url,
        "salary": salary,
        "skills": skills,
        "tailored_resume": tailored_str,
    }
