#!/usr/bin/env python3
"""
main.py - Unified Command-Line Interface for the Job Application Automation Platform.

Architecture:
- src.config: Centralized paths, candidate credentials & settings.
- src.core: Role classification, ATS resume tailoring & daily workflow orchestration.
- src.db: SQLite repository and application tracking.
- src.appliers: Platform automation engines (Wellfound v2.0, Internshala REST API, WWR, Naukri, Ashby, Lever, Greenhouse).
- src.outreach: 100% account-safe LinkedIn recruiter & founder outreach generator.
- src.notifications: WhatsApp delivery (WhatsApp Web Playwright, CallMeBot, Windows URI).

Commands:
    python main.py workflow [--platform PLATFORM] [--submit] [--count 20]
    python main.py apply [--url URL | --job-id ID | --batch N] [--submit] [--headless]
    python main.py outreach [--limit 15] [--phone PHONE]
    python main.py stats
    python main.py tailor --company COMPANY --title TITLE [--jd JD_TEXT]
    python main.py login <wellfound | internshala | wwr | whatsapp>
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from src.config import (
    ACTIVE_PLATFORMS,
    CANDIDATE_EMAIL,
    CANDIDATE_NAME,
    DB_PATH,
    DEFAULT_PHONE,
    LOGS_DIR,
    RESUMES_DIR,
)
from src.core.classifier import classify_role, is_target_role
from src.core.tailor import get_or_create_resume
from src.core.workflow import human_delay, run_daily_workflow
from src.db.repository import get_connection, get_platform_jobs, get_stats, seed_sample_jobs
from src.appliers.router import apply_to_job
from src.outreach.linkedin import run_linkedin_outreach
from src.notifications.whatsapp import login_interactive as login_whatsapp_interactive


def cmd_stats(args):
    """Displays real-time pipeline statistics from jobs.db."""
    stats = get_stats()
    print("=" * 60)
    print("           JOB APPLICATION PIPELINE METRICS")
    print(f"           Candidate: {CANDIDATE_NAME} (+{DEFAULT_PHONE})")
    print("=" * 60)
    print(f"\n📊 Total Records in Database: {stats['total_jobs']}")

    print("\n📁 Applications by Status:")
    for status, count in sorted(stats['status_counts'].items(), key=lambda x: x[1], reverse=True):
        print(f"   • {status:<20}: {count:>5}")

    print("\n🌐 Active Platforms (Daily Target: 20 each = 40 total):")
    for platform in ACTIVE_PLATFORMS:
        count = stats['platform_counts'].get(platform, 0)
        applied = stats['applied_by_platform'].get(platform, 0)
        print(f"   • {platform.capitalize():<15}: {count:>5} total ({applied:>3} applied)")

    other_platforms = [p for p in stats['platform_counts'] if p not in ACTIVE_PLATFORMS]
    if other_platforms:
        print("\n📦 Decommissioned Platforms (Archived):")
        for platform in sorted(other_platforms):
            count = stats['platform_counts'].get(platform, 0)
            applied = stats['applied_by_platform'].get(platform, 0)
            print(f"   • {platform.capitalize():<15}: {count:>5} total ({applied:>3} applied)")

    print("\n🎯 Priority Targets (Tier 1-3):")
    tier_labels = {1: "GenAI Engineer", 2: "AI Engineer / Applied AI", 3: "AI Agent / Agentic AI"}
    for tier, count in sorted(stats['tier_counts'].items()):
        label = tier_labels.get(tier, f"Tier {tier}")
        print(f"   • Tier {tier} ({label}): {count:>5}")
    print("=" * 60)


def cmd_tailor(args):
    """Generates an ATS-tailored resume for a target job."""
    print(f"Tailoring ATS resume for {args.company} - {args.title}...")
    pdf_path = get_or_create_resume(company=args.company, title=args.title, notes=args.jd or "")
    print(f"✅ Generated ATS PDF: {pdf_path}")


def cmd_apply(args):
    """Executes single or batch job applications."""
    if args.batch:
        con = get_connection()
        placeholders = ",".join("?" for _ in ACTIVE_PLATFORMS)
        rows = con.execute(
            f"SELECT id, company, title, url, notes FROM jobs WHERE status IN ('new', 'login_required') AND source IN ({placeholders}) ORDER BY llm_score DESC, kw_score DESC LIMIT ?",
            (*ACTIVE_PLATFORMS, args.batch)
        ).fetchall()
        if not rows:
            print(f"No new jobs from {', '.join(p.capitalize() for p in ACTIVE_PLATFORMS)} to apply to in jobs.db.")
            return
        print(f"Processing batch of {len(rows)} jobs ({', '.join(p.capitalize() for p in ACTIVE_PLATFORMS)})...")
        for idx, row in enumerate(rows, 1):
            apply_to_job(
                row["url"],
                company=row["company"],
                title=row["title"],
                notes=row["notes"] or "",
                submit=args.submit,
                headless=args.headless
            )
            if idx < len(rows):
                human_delay(context=f"Batch #{idx}/{len(rows)}")
        return

    target_url = args.url
    comp = args.company or "Company"
    title = args.title or "AI Engineer"
    notes = ""

    if args.job_id:
        con = get_connection()
        row = con.execute("SELECT company, title, url, notes FROM jobs WHERE id=?", (args.job_id,)).fetchone()
        if not row:
            sys.exit(f"Job {args.job_id} not found in jobs.db.")
        comp, title, target_url, notes = row["company"], row["title"], row["url"], row["notes"] or ""

    if not target_url:
        sys.exit("Error: Please provide --url, --job-id, or --batch.")

    apply_to_job(target_url, company=comp, title=title, notes=notes, submit=args.submit, headless=args.headless)


def cmd_workflow(args):
    """Runs the daily application workflow."""
    submit_mode = not getattr(args, "stage", False)
    run_daily_workflow(
        submit=submit_mode,
        jobs_per_platform=args.count,
        phone=args.phone,
        platform=args.platform
    )


def cmd_outreach(args):
    """Generates LinkedIn recruiter & founder outreach queue."""
    run_linkedin_outreach(limit=args.limit, phone=args.phone)


def cmd_login(args):
    """Opens visible browser to log into specified platform."""
    platform = args.platform.lower().strip()
    if platform == "whatsapp":
        login_whatsapp_interactive()
        return

    from playwright.sync_api import sync_playwright
    profile_dir = Path.home() / ".chrome_job_profile"

    login_urls = {
        "wellfound": "https://wellfound.com/login",
        "internshala": "https://internshala.com/login/student"
    }

    if platform not in login_urls:
        sys.exit(f"Unknown platform '{platform}'. Choose from: wellfound, internshala, whatsapp")

    target_url = login_urls[platform]
    print(f"\nOpening Chrome to log into {platform.capitalize()}...")
    print(f"URL: {target_url}")
    print("Please complete login in the opened browser window. When finished, you can close the window.\n")

    with sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                channel="chrome",
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
                ignore_default_args=["--enable-automation"],
                viewport={"width": 1280, "height": 900}
            )
        except Exception:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
                ignore_default_args=["--enable-automation"],
                viewport={"width": 1280, "height": 900}
            )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(target_url)

        try:
            while len(ctx.pages) > 0 and not page.is_closed():
                time.sleep(1)
        except (KeyboardInterrupt, Exception):
            pass
        finally:
            try: ctx.close()
            except Exception: pass

    print(f"\nSession saved to {profile_dir}!")


def main():
    parser = argparse.ArgumentParser(
        description="Unified Job Application & Outreach Automation System (Pipeline v2.0)",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Workflow command
    wf_parser = subparsers.add_parser("workflow", help="Run master daily job application workflow")
    wf_parser.add_argument("--platform", type=str, default=None, choices=["internshala", "wellfound"], help="Target specific platform (default: both internshala and wellfound)")
    wf_parser.add_argument("--submit", action="store_true", default=True, help="Auto-submit applications directly (default: True)")
    wf_parser.add_argument("--stage", action="store_true", help="Stage applications for review without auto-submitting")
    wf_parser.add_argument("--count", type=int, default=20, help="Number of jobs per platform (default: 20)")
    wf_parser.add_argument("--phone", type=str, default=None, help="WhatsApp notification recipient phone")

    # Apply command
    app_parser = subparsers.add_parser("apply", help="Apply to a specific job or batch")
    app_parser.add_argument("--url", type=str, help="Direct job application URL")
    app_parser.add_argument("--job-id", type=str, help="Job ID from jobs.db")
    app_parser.add_argument("--company", type=str, default="Company", help="Company name")
    app_parser.add_argument("--title", type=str, default="AI Engineer", help="Job title")
    app_parser.add_argument("--submit", action="store_true", help="Auto-submit application")
    app_parser.add_argument("--batch", type=int, help="Stage top N new jobs from jobs.db")
    app_parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")

    # Outreach command
    out_parser = subparsers.add_parser("outreach", help="Generate LinkedIn recruiter & founder outreach queue")
    out_parser.add_argument("--limit", type=int, default=15, help="Number of companies (default: 15)")
    out_parser.add_argument("--phone", type=str, default=None, help="WhatsApp notification recipient phone")

    # Stats command
    subparsers.add_parser("stats", help="Display application pipeline statistics")

    # Tailor command
    t_parser = subparsers.add_parser("tailor", help="Generate ATS PDF resume for a specific job")
    t_parser.add_argument("--company", type=str, required=True, help="Target company name")
    t_parser.add_argument("--title", type=str, required=True, help="Target job title")
    t_parser.add_argument("--jd", type=str, default="", help="Job description text or requirements")

    # Login command
    log_parser = subparsers.add_parser("login", help="Log into a platform browser profile")
    log_parser.add_argument("platform", choices=["wellfound", "internshala", "whatsapp"], help="Platform to log into")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "workflow":
        cmd_workflow(args)
    elif args.command == "apply":
        cmd_apply(args)
    elif args.command == "outreach":
        cmd_outreach(args)
    elif args.command == "stats":
        cmd_stats(args)
    elif args.command == "tailor":
        cmd_tailor(args)
    elif args.command == "login":
        cmd_login(args)


if __name__ == "__main__":
    main()
