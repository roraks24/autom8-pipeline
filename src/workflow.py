import datetime
import logging
import random
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from src.appliers.router import apply_to_job
from src.config import (
    ACTIVE_PLATFORMS,
    APPLIED_DB_PATH,
    CANDIDATE_NAME,
    DAILY_TARGET_PER_PLATFORM,
    DEFAULT_PHONE,
    HUMAN_DELAY_MAX,
    HUMAN_DELAY_MIN,
)
from src.core.classifier import classify_role, is_unpaid_role
from src.discovery.internshala import discover_live_internshala_jobs
from src.discovery.wellfound import discover_live_wellfound_jobs
from src.notifications.reporter import (
    build_whatsapp_summary,
    extract_salary_from_desc,
    extract_skills_from_desc,
    print_console_summary,
    send_daily_report,
)
from src.notifications.whatsapp import load_config, normalize_phone
from src.outreach.linkedin import run_linkedin_outreach
from src.storage.applied_store import AppliedJobsStore, SkippedCacheStore

logger = logging.getLogger("workflow")


def human_delay(min_sec: float = HUMAN_DELAY_MIN, max_sec: float = HUMAN_DELAY_MAX, context: str = "") -> None:
    """Pauses with randomized human-like jitter between consecutive applications."""
    delay = round(random.uniform(min_sec, max_sec), 1)
    label = f" ({context})" if context else ""
    print(f"  [Human Delay] Pausing {delay}s before next application{label}...", flush=True)
    time.sleep(delay)


def _discover_for_platform(
    platform: str,
    limit: int,
    applied_store: AppliedJobsStore,
    skipped_store: SkippedCacheStore,
    seen_urls: Set[str],
) -> List[Dict[str, Any]]:
    if platform == "wellfound":
        return discover_live_wellfound_jobs(
            limit=limit,
            applied_store=applied_store,
            skipped_store=skipped_store,
            seen_urls=seen_urls,
        )
    if platform == "internshala":
        return discover_live_internshala_jobs(
            limit=limit,
            applied_store=applied_store,
            skipped_store=skipped_store,
            seen_urls=seen_urls,
            verify_eligibility=True,
        )
    return []


def _resolve_platforms(platform: Optional[str]) -> List[str]:
    if not platform:
        return list(ACTIVE_PLATFORMS)
    p_clean = platform.lower().strip()
    if p_clean in ACTIVE_PLATFORMS:
        return [p_clean]
    matched = [p for p in ACTIVE_PLATFORMS if p_clean in p]
    return matched if matched else [p_clean]


def run_daily_workflow(
    submit: bool = True,
    jobs_per_platform: int = DAILY_TARGET_PER_PLATFORM,
    phone: Optional[str] = None,
    platform: Optional[str] = None,
    respect_daily_quota: bool = True,
    send_whatsapp_notify: bool = True,
    with_outreach: bool = False,
) -> Tuple[List[Dict[str, Any]], str]:
    """
    Executes the full automated pipeline end-to-end:
    Discovery -> Compensation/Tier Filter -> ATS Resume Tailoring -> Apply ->
    Persist to single JSON DB (data/applied_jobs.json) -> Console & WhatsApp Summary.
    """
    cfg = load_config()
    target_phone = normalize_phone(phone or cfg.get("preferred_target") or cfg.get("primary_phone") or DEFAULT_PHONE)
    platforms = _resolve_platforms(platform)

    applied_store = AppliedJobsStore()
    skipped_store = SkippedCacheStore()
    applied_records: List[Dict[str, Any]] = []
    platform_desc = f"{len(platforms)} Platform(s) ({', '.join(p.capitalize() for p in platforms)})"

    print("=" * 72)
    print(f"   AUTOM8 JOB APPLICATION PIPELINE ({len(platforms)} PLATFORM(S) x {jobs_per_platform} DAILY TARGET)")
    print(f"   Platforms : {', '.join(p.capitalize() for p in platforms)}")
    print(f"   Mode      : {'[LIVE AUTO-SUBMIT]' if submit else '[STAGE ONLY - NO SUBMIT]'}")
    print(f"   Candidate : {CANDIDATE_NAME}")
    print(f"   Database  : {APPLIED_DB_PATH} (JSON-only | Zero Screenshots)")
    print(f"   WhatsApp  : +{target_phone if send_whatsapp_notify else 'Disabled'}")
    print("=" * 72)

    today_str = datetime.date.today().isoformat()

    for idx_p, p_name in enumerate(platforms):
        done_today = len(applied_store.get_applied_today(source=p_name, date_str=today_str)) if respect_daily_quota else 0
        target_for_run = max(0, jobs_per_platform - done_today) if respect_daily_quota else jobs_per_platform

        if target_for_run == 0:
            print(f"\n>>> Platform: {p_name.upper()} — Daily quota already met ({done_today}/{jobs_per_platform}). Skipping.")
            continue

        print(f"\n>>> Processing Platform: {p_name.upper()} (Target: {target_for_run} | Done today: {done_today}/{jobs_per_platform}) <<<")

        seen_urls: Set[str] = set()
        candidate_queue: List[Dict[str, Any]] = []
        successful_count = 0
        processed_count = 0
        discovery_passes = 0
        max_discovery_passes = 6
        max_attempts = max(target_for_run * 6, 80)

        while successful_count < target_for_run and processed_count < max_attempts:
            needed = target_for_run - successful_count

            if not candidate_queue:
                if discovery_passes >= max_discovery_passes:
                    print(f"\n  [Notice] Exhausted live discovery passes ({max_discovery_passes}). Achieved {successful_count}/{target_for_run}.")
                    break
                discovery_passes += 1
                print(f"\n  [Discovery Pass {discovery_passes}/{max_discovery_passes}] Seeking {needed} target role(s) on {p_name.capitalize()}...")
                try:
                    fresh = _discover_for_platform(
                        p_name,
                        limit=max(needed * 2, 20),
                        applied_store=applied_store,
                        skipped_store=skipped_store,
                        seen_urls=seen_urls,
                    )
                    candidate_queue.extend(fresh)
                except Exception as e:
                    logger.warning(f"Discovery failed on {p_name}: {e}")

                if not candidate_queue:
                    print(f"\n  [Notice] No additional fresh target roles available on {p_name.capitalize()}. Achieved {successful_count}/{target_for_run}.")
                    break

            job = candidate_queue.pop(0)
            processed_count += 1

            comp = job.get("company") or "Company"
            title = job.get("title") or "AI / Python Engineer"
            url = job.get("url") or ""
            notes = job.get("notes") or ""
            clean_desc = re.sub(r";\s*App status:.*$", "", notes, flags=re.I)

            tier = job.get("target_tier")
            cat = job.get("target_category")
            if not tier:
                tier, cat, _ = classify_role(title, clean_desc, url=url, source=p_name)
                tier = tier or 2
                cat = cat or "AI Engineer / Developer"

            salary = job.get("salary") or extract_salary_from_desc(clean_desc)
            if is_unpaid_role(text=clean_desc, title=title, salary=salary):
                print(f"  [Policy Filter] Skipping {comp} - {title}: Unpaid role excluded.")
                skipped_store.record_skipped(
                    url=url, job_id=job.get("id", ""), source=p_name,
                    company=comp, title=title, status="unpaid_excluded", reason="Unpaid role"
                )
                continue

            skills_req = job.get("skills") or extract_skills_from_desc(clean_desc, title)

            print(f"\n[{p_name.upper()} #{processed_count}] [Tier {tier}: {cat}] {comp} - {title}", flush=True)
            print(f"  Progress: {successful_count}/{target_for_run} | Salary: {salary} | Skills: {skills_req}", flush=True)

            try:
                res = apply_to_job(
                    url=url,
                    company=comp,
                    title=title,
                    notes=clean_desc,
                    salary=salary,
                    skills=skills_req,
                    location=job.get("location", "Remote / India"),
                    job_id=job.get("id", ""),
                    target_tier=tier,
                    target_category=cat,
                    submit=submit,
                    headless=True,
                    applied_store=applied_store,
                    skipped_store=skipped_store,
                )
                status = res.get("status", "failed")
                app_id = res.get("application_id")
            except Exception as e:
                logger.error(f"  ! Application error for {comp}: {e}")
                status = "failed"
                app_id = None

            is_success = (submit and status == "applied") or (not submit and status in ("staged_for_review", "applied"))
            if is_success:
                successful_count += 1
                id_info = f" (App ID: {app_id})" if app_id else ""
                print(f"  ✅ [Target Met: {successful_count}/{target_for_run}] {comp}{id_info}", flush=True)
            else:
                print(f"  ⚠️ [Replenishing] {comp} -> '{status}'. Seeking next role...", flush=True)

            applied_records.append({
                "platform": p_name.capitalize(),
                "company": comp,
                "role": title,
                "tier": tier,
                "target_category": cat,
                "salary": salary,
                "skills_required": skills_req,
                "status": status,
                "application_id": app_id,
                "url": url,
            })

            if successful_count < target_for_run and processed_count < max_attempts:
                human_delay(context=f"{p_name.capitalize()} #{processed_count} ({successful_count}/{target_for_run})")

        if idx_p < len(platforms) - 1:
            shift_delay = round(random.uniform(20.0, 35.0), 1)
            print(f"\n[Platform Transition] Completed {p_name.capitalize()}. Pausing {shift_delay}s...", flush=True)
            time.sleep(shift_delay)

    print_console_summary(applied_records, str(APPLIED_DB_PATH))

    wa_text = build_whatsapp_summary(applied_records, platform_desc=platform_desc)
    if send_whatsapp_notify and applied_records:
        print(f"\nDispatching summary to WhatsApp (+{target_phone})...")
        send_daily_report(wa_text, phone=target_phone)

    if with_outreach:
        print("\n[Outreach] Generating Tier 1/3 LinkedIn outreach queue...")
        run_linkedin_outreach(limit=10, phone=target_phone, send_wa=send_whatsapp_notify)

    return applied_records, wa_text
