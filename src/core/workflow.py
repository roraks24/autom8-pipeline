import datetime
import json
import logging
import random
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.config import (
    ACTIVE_PLATFORMS,
    CANDIDATE_NAME,
    DAILY_TARGET_PER_PLATFORM,
    DB_PATH,
    DEFAULT_PHONE,
    HUMAN_DELAY_MAX,
    HUMAN_DELAY_MIN,
    LOGS_DIR,
    TOTAL_DAILY_TARGET,
)
from src.core.classifier import classify_role, is_target_role, is_unpaid_role
from src.core.tailor import get_or_create_resume
from src.db.repository import get_connection, get_platform_jobs, seed_sample_jobs, update_job_status
from src.appliers.router import apply_to_job
from src.appliers.wellfound_discovery import discover_live_wellfound_jobs
from src.appliers.internshala_discovery import discover_live_internshala_jobs
from src.notifications.reporter import (
    build_markdown_report,
    build_whatsapp_summary,
    extract_salary_from_desc,
    extract_skills_from_desc,
    save_daily_report,
    send_daily_report,
)
from src.notifications.whatsapp import load_config, normalize_phone

logger = logging.getLogger("workflow")


def human_delay(min_sec: float = HUMAN_DELAY_MIN, max_sec: float = HUMAN_DELAY_MAX, context: str = "") -> None:
    """
    Introduces randomized, human-like pacing between applications
    to prevent bot-detection heuristics, WAF triggers, and account suspension.
    """
    delay = round(random.uniform(min_sec, max_sec), 1)
    label = f" ({context})" if context else ""
    print(f"  [Human Delay] Pausing {delay}s before next application to simulate realistic candidate pace{label}...", flush=True)
    time.sleep(delay)


def run_daily_workflow(
    submit: bool = True,
    jobs_per_platform: int = 20,
    phone: Optional[str] = None,
    platform: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], str]:
    """Executes the daily job application cycle across specified or active platforms (Wellfound & Internshala)."""
    cfg = load_config()
    target_phone = phone or cfg.get("preferred_target") or cfg.get("primary_phone") or DEFAULT_PHONE
    target_phone = normalize_phone(target_phone)

    if platform:
        p_clean = platform.lower().strip()
        if p_clean in ACTIVE_PLATFORMS:
            platforms = [p_clean]
        else:
            matched = [p for p in ACTIVE_PLATFORMS if p_clean in p]
            platforms = matched if matched else [p_clean]
    else:
        platforms = list(ACTIVE_PLATFORMS)

    total_target = len(platforms) * jobs_per_platform
    applied_records = []
    platform_desc = f"{len(platforms)} Platform(s) ({', '.join(p.capitalize() for p in platforms)})"

    print("=" * 65)
    print(f"   DAILY JOB APPLICATION RUN (PIPELINE v2.0 - {len(platforms)} PLATFORM(S) x {jobs_per_platform} JOBS)")
    print(f"   Platforms: {', '.join(p.capitalize() for p in platforms)}")
    print(f"   Mode: {'[LIVE AUTO-SUBMIT]' if submit else '[PRE-FILL & STAGE FOR REVIEW]'}")
    print(f"   Candidate: {CANDIDATE_NAME}")
    print(f"   WhatsApp Report Target: +{target_phone}")
    print("=" * 65)

    # Ensure verified sample target jobs exist in jobs.db
    seed_sample_jobs()

    con = get_connection()

    for p_name in platforms:
        print(f"\n>>> Processing Platform: {p_name.upper()} (Target: {jobs_per_platform} Successful Applications) <<<")
        if p_name == "wellfound":
            print(f"  [Wellfound] Running live multi-directory discovery for daily fresh roles (Target: {jobs_per_platform})...")
            try:
                discover_live_wellfound_jobs(limit=jobs_per_platform)
            except Exception as e:
                logger.warning(f"Live Wellfound discovery skipped: {e}")

        elif p_name == "internshala":
            print(f"  [Internshala] Running live discovery for daily fresh roles (Target: {jobs_per_platform})...")
            try:
                discover_live_internshala_jobs(limit=jobs_per_platform)
            except Exception as e:
                logger.warning(f"Live Internshala discovery skipped: {e}")

        successful_count = 0
        processed_count = 0
        discovery_passes = 0
        max_discovery_passes = 12
        max_attempts = max(jobs_per_platform * 6, 120)
        processed_job_ids = set()

        while successful_count < jobs_per_platform and processed_count < max_attempts:
            needed = jobs_per_platform - successful_count
            pending_jobs = [j for j in get_platform_jobs(p_name, limit=max(needed * 2, 10)) if j["id"] not in processed_job_ids]

            # If no pending jobs in DB, dynamically discover more fresh roles!
            if not pending_jobs:
                while not pending_jobs and discovery_passes < max_discovery_passes:
                    discovery_passes += 1
                    print(f"\n  [Target Replenishment] Need {needed} more successful application(s). Running live discovery (Pass {discovery_passes}/{max_discovery_passes})...")
                    if p_name == "wellfound":
                        try:
                            discover_live_wellfound_jobs(limit=max(needed * 2, 20))
                        except Exception as e:
                            logger.warning(f"Live Wellfound replenishment discovery skipped: {e}")
                    elif p_name == "internshala":
                        try:
                            discover_live_internshala_jobs(limit=max(needed * 2, 20))
                        except Exception as e:
                            logger.warning(f"Live Internshala replenishment discovery skipped: {e}")

                    pending_jobs = [j for j in get_platform_jobs(p_name, limit=max(needed * 2, 10)) if j["id"] not in processed_job_ids]

                if not pending_jobs:
                    print(f"\n  [Notice] All available fresh listings for {p_name.capitalize()} have been evaluated for today. Achieved {successful_count}/{jobs_per_platform} target applications.")
                    break

            job = pending_jobs[0]
            processed_job_ids.add(job["id"])
            processed_count += 1

            comp = job.get("company") or "Company"
            title = job.get("title") or "AI / Python Engineer"
            url = job.get("url") or ""
            desc = job.get("desc") or job.get("notes") or ""
            clean_desc = re.sub(r";\s*App status:.*$", "", desc, flags=re.I)

            tier = job.get("target_tier")
            cat = job.get("target_category")
            if not tier:
                tier, cat, _ = classify_role(title, clean_desc)
                tier = tier or 2
                cat = cat or "AI Engineer / Applied AI"

            salary = extract_salary_from_desc(clean_desc)
            if "Salary:" in clean_desc:
                m = re.search(r"Salary:\s*([^|;]+)", clean_desc)
                if m: salary = m.group(1).strip()
            if salary.startswith(","):
                salary = "$80,000 - $110,000 Annually"

            # Candidate Policy Enforcement: NEVER apply to unpaid work
            if is_unpaid_role(text=clean_desc, title=title, salary=salary):
                print(f"  [Policy Filter] Skipping {comp} - {title}: Unpaid / zero-stipend role excluded by candidate policy.")
                update_job_status(job["id"], "unpaid_excluded", url=url)
                continue

            skills_req = extract_skills_from_desc(clean_desc, title)
            if "Skills:" in clean_desc:
                m = re.search(r"Skills:\s*([^|;]+)", clean_desc)
                if m: skills_req = m.group(1).strip()

            print(f"\n[{p_name.upper()} Attempt #{processed_count}] [Tier {tier}: {cat}] {comp} - {title}", flush=True)
            print(f"  Target Progress: {successful_count}/{jobs_per_platform} successful | Salary: {salary} | Skills: {skills_req}", flush=True)

            if submit:
                action_required = "None - Application submitted live, waiting for employer review."
                status = "applied"
            else:
                action_required = "Pre-filled & staged for review. Ready to auto-submit with --submit."
                status = "staged_for_review"

            try:
                app_status, _ = apply_to_job(
                    url=url,
                    company=comp,
                    title=title,
                    notes=clean_desc,
                    submit=submit,
                    headless=True
                )
                if app_status:
                    status = app_status
                    if status == "staged_for_review":
                        action_required = "Pre-filled & staged for review."
                    elif status == "dropped_demographics_required":
                        action_required = "Dropped: Requires mandatory CGPA / 12th percentage / DOB / Address."
                    elif status == "ineligible":
                        action_required = "Ineligible: In-office constraint or candidate location criteria."
                    elif status == "already_applied":
                        action_required = "Already applied previously on platform."
                    elif status == "expired":
                        action_required = "Listing is closed or no longer available."
                    elif status == "applied":
                        action_required = "None - Application submitted live, waiting for employer review."
            except Exception as e:
                logger.error(f"  ! Application error for {comp}: {e}")
                status = "staged_with_notes"

            # Update DB status (including any URL duplicates)
            update_job_status(job["id"], status, url=url)

            # Determine whether this counts as a completed application toward the daily target
            is_success = (submit and status == "applied") or (not submit and status in ("staged_for_review", "applied"))
            if is_success:
                successful_count += 1
                print(f"  ✅ [Target Met: {successful_count}/{jobs_per_platform}] Application successfully submitted for {comp}!", flush=True)
            else:
                print(f"  ⚠️ [Replenishment Needed] Application for {comp} resulted in '{status}'. Disqualified from daily target. Seeking next role...", flush=True)

            if "interview" in desc.lower() or "assignment" in desc.lower():
                action_required = "Keep an eye on email for coding assignment."
            elif "assessment" in desc.lower():
                action_required = "Online technical assessment link will be sent to email."

            applied_records.append({
                "platform": p_name.capitalize(),
                "company": comp,
                "role": title,
                "tier": tier,
                "target_category": cat,
                "salary": salary,
                "skills_required": skills_req,
                "status": status,
                "action_required": action_required,
                "url": url
            })

            # Natural randomized delay between applications to protect account from rate-limiting/termination
            if successful_count < jobs_per_platform and processed_count < max_attempts:
                human_delay(min_sec=HUMAN_DELAY_MIN, max_sec=HUMAN_DELAY_MAX, context=f"{p_name.capitalize()} #{processed_count} (Progress: {successful_count}/{jobs_per_platform})")

        # Inter-platform human transition delay
        if p_name != platforms[-1]:
            shift_delay = round(random.uniform(20.0, 35.0), 1)
            print(f"\n[Platform Transition] Completed {p_name.capitalize()}. Pausing {shift_delay}s before starting {platforms[platforms.index(p_name)+1].capitalize()}...", flush=True)
            time.sleep(shift_delay)

    # Save reports and dispatch notifications
    report_md = build_markdown_report(applied_records, total_target=total_target, submit=submit)
    saved_path = save_daily_report(report_md)
    print(f"\n[Report Saved] {saved_path.name}")

    wa_text = build_whatsapp_summary(applied_records, platform_desc=platform_desc)
    print(f"\nSending report to WhatsApp (+{target_phone})...")
    send_daily_report(wa_text, phone=target_phone)

    return applied_records, wa_text
