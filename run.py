#!/usr/bin/env python3
"""
run.py - Single Unified Entrypoint for the Autom8 Job Application Pipeline.

Runs the complete pipeline end-to-end by default:
    Discovery -> Compensation/Tier Filter -> ATS Resume Tailoring -> Apply ->
    Single JSON DB (data/applied_jobs.json) -> WhatsApp Notification (Zero Screenshots).

Usage:
    python run.py                                  # Run full daily pipeline (20 Internshala + 20 Wellfound)
    python run.py --platform wellfound --count 10  # Run specific platform & target
    python run.py --stage                          # Pre-fill & stage only without submitting
    python run.py --force --count 5                # Apply 5 additional jobs ignoring daily cap
    python run.py stats                            # Show JSON database metrics
    python run.py history --date 2026-11-24        # List applied jobs from JSON DB
    python run.py discover --platform internshala  # Preview eligible paid roles
    python run.py apply --url <URL>                # Apply to a single job URL
    python run.py tailor --company X --title Y     # Generate a tailored ATS PDF resume
    python run.py outreach [--limit 15]            # Generate LinkedIn outreach queue
    python run.py login <wellfound|internshala|whatsapp>
"""

import argparse
import datetime
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from src.appliers.internshala import sync_internshala_outcomes
from src.appliers.router import apply_to_job
from src.config import ACTIVE_PLATFORMS, CANDIDATE_NAME, DAILY_TARGET_PER_PLATFORM, DEFAULT_PHONE
from src.core.browser import open_interactive_login
from src.core.tailor import get_or_create_resume
from src.discovery.internshala import discover_live_internshala_jobs
from src.discovery.wellfound import discover_live_wellfound_jobs
from src.notifications.whatsapp import login_interactive as login_whatsapp_interactive
from src.outreach.linkedin import run_linkedin_outreach
from src.storage.applied_store import AppliedJobsStore, SkippedCacheStore
from src.workflow import run_daily_workflow

SUBCOMMANDS = {"pipeline", "stats", "history", "discover", "apply", "tailor", "outreach", "sync", "login"}


def cmd_pipeline(args: argparse.Namespace) -> None:
    """Runs the full end-to-end daily application workflow."""
    run_daily_workflow(
        submit=not args.stage,
        jobs_per_platform=args.count,
        phone=args.phone,
        platform=args.platform,
        respect_daily_quota=not args.force,
        send_whatsapp_notify=not args.no_whatsapp,
        with_outreach=args.with_outreach,
    )


def cmd_stats(_: argparse.Namespace) -> None:
    """Displays pipeline metrics from data/applied_jobs.json and data/skipped_cache.json."""
    applied_store = AppliedJobsStore()
    skipped_store = SkippedCacheStore()
    stats = applied_store.get_stats()
    skip_stats = skipped_store.get_stats()

    print("=" * 68)
    print("           AUTOM8 PIPELINE METRICS (JSON-ONLY STORAGE)")
    print(f"           Candidate : {CANDIDATE_NAME} (+{DEFAULT_PHONE})")
    print(f"           Applied DB: {stats['db_path']}")
    print("=" * 68)
    print(f"\n📊 Total Applied Jobs (Unique): {stats['total_applied']}")
    print(f"📅 Applied Today ({stats['today_date']}): {stats['today_total']}/{DAILY_TARGET_PER_PLATFORM * len(ACTIVE_PLATFORMS)}")

    print("\n🌐 By Active Platform:")
    for plat in ACTIVE_PLATFORMS:
        total_p = stats["by_platform"].get(plat, 0)
        today_p = stats["today_by_platform"].get(plat, 0)
        print(f"   • {plat.capitalize():<14}: {total_p:>4} total | {today_p:>2}/{DAILY_TARGET_PER_PLATFORM} today")

    other = {k: v for k, v in stats["by_platform"].items() if k not in ACTIVE_PLATFORMS}
    if other:
        print("\n📦 Historical Archived Platforms:")
        for plat, cnt in sorted(other.items()):
            print(f"   • {plat.capitalize():<14}: {cnt:>4} total")

    tier_labels = {1: "GenAI Engineer", 2: "AI / Full-Stack / Backend Engineer", 3: "AI Agent / Agentic AI"}
    print("\n🎯 Applied Breakdown by Priority Tier:")
    for tier, count in sorted(stats["tier_counts"].items()):
        print(f"   • Tier {tier} ({tier_labels.get(tier, f'Tier {tier}')}): {count:>4}")

    outcomes = stats.get("outcome_counts") or {}
    if outcomes:
        print("\n📬 Synced Application Outcomes:")
        for status_label, count in sorted(outcomes.items(), key=lambda x: (-x[1], x[0])):
            print(f"   • {status_label:<28}: {count:>4}")

    print(f"\n🚫 Skip-Cache ({skip_stats['cache_path']}): {skip_stats['total_skipped']} cached exclusions")
    for status, cnt in list(skip_stats["by_status"].items())[:6]:
        print(f"   • {status:<28}: {cnt:>4}")
    print("=" * 68)


def cmd_history(args: argparse.Namespace) -> None:
    """Lists applied job entries from data/applied_jobs.json."""
    store = AppliedJobsStore()
    jobs = store.get_all(source=args.platform, date_str=args.date, limit=args.limit)
    print(f"\nShowing {len(jobs)} applied job(s) from data/applied_jobs.json:\n")
    for idx, j in enumerate(jobs, 1):
        aid = f" | ID: {j['application_id']}" if j.get("application_id") else ""
        sal = j.get("salary") or "Competitive"
        print(f"{idx:>3}. [{j.get('applied_at')}] [{j.get('source', '').capitalize()}] {j.get('company')} — {j.get('title')} ({sal}){aid}")


def cmd_discover(args: argparse.Namespace) -> None:
    """Pre-scans platforms to preview eligible paid jobs without applying."""
    platforms = [args.platform] if args.platform else list(ACTIVE_PLATFORMS)
    applied_store = AppliedJobsStore()
    skipped_store = SkippedCacheStore()

    for plat in platforms:
        print(f"\nScanning {plat.capitalize()} (limit={args.limit})...")
        if plat == "internshala":
            jobs = discover_live_internshala_jobs(limit=args.limit, applied_store=applied_store, skipped_store=skipped_store)
        else:
            jobs = discover_live_wellfound_jobs(limit=args.limit, applied_store=applied_store, skipped_store=skipped_store)

        for idx, j in enumerate(jobs, 1):
            print(f"  {idx:>2}. [Tier {j['target_tier']}] {j['company']} — {j['title']} ({j['salary']})")
            print(f"      {j['url']}")


def cmd_apply(args: argparse.Namespace) -> None:
    """Applies to a single specified URL."""
    res = apply_to_job(
        url=args.url,
        company=args.company,
        title=args.title,
        notes=args.jd or "",
        submit=not args.stage,
        headless=not args.visible,
        enforce_active=not args.allow_external,
    )
    print(f"\nResult: {res.get('status')} — {res.get('company')} ({res.get('title')})")


def cmd_tailor(args: argparse.Namespace) -> None:
    """Generates a tailored ATS PDF resume."""
    pdf_path = get_or_create_resume(company=args.company, title=args.title, notes=args.jd or "")
    print(f"\nGenerated ATS PDF: {pdf_path}")


def cmd_outreach(args: argparse.Namespace) -> None:
    """Generates LinkedIn outreach queue from applied_jobs.json."""
    run_linkedin_outreach(limit=args.limit, phone=args.phone, send_wa=not args.no_whatsapp)


def cmd_sync(args: argparse.Namespace) -> None:
    """Syncs live Internshala dashboard statuses back into data/applied_jobs.json."""
    print("=" * 68)
    print("           AUTOM8 OUTCOME SYNC (INTERNSHALA -> APPLIED DB)")
    print("=" * 68)
    res = sync_internshala_outcomes(max_pages=args.pages)
    print(
        f"\n🔄 Scanned {res['pages_fetched']}/{res['total_pages_available']} dashboard pages "
        f"({res['apps_scanned']} applications)."
    )
    print(f"💾 Records updated in data/applied_jobs.json: {res['updated']}")

    if res["status_counts"]:
        print("\n📊 Live Dashboard Status Breakdown (Scanned Pages):")
        for st, cnt in sorted(res["status_counts"].items(), key=lambda x: (-x[1], x[0])):
            print(f"   • {st:<26}: {cnt:>4}")

    if res["positive_leads"]:
        print("\n🌟 Active Leads / Action Required:")
        for lead in res["positive_leads"]:
            extra = []
            if lead.get("interview_link"):
                extra.append(f"Interview: {lead['interview_link']}")
            if lead.get("assignment_link"):
                extra.append(f"Chat/Assignment: {lead['assignment_link']}")
            extra_str = f" | {' ; '.join(extra)}" if extra else ""
            print(f"   • [{lead['status']}] {lead['company']} — {lead['title']} ({lead.get('applied_at')}){extra_str}")

    db_outcomes = res.get("db_outcome_counts") or {}
    if db_outcomes:
        print("\n📬 Overall Synced Outcomes in data/applied_jobs.json:")
        for st, cnt in sorted(db_outcomes.items(), key=lambda x: (-x[1], x[0])):
            print(f"   • {st:<26}: {cnt:>4}")
    print("=" * 68)


def cmd_login(args: argparse.Namespace) -> None:
    """Opens browser for one-time interactive authentication."""
    if args.platform == "whatsapp":
        login_whatsapp_interactive()
    else:
        open_interactive_login(args.platform)


def _add_pipeline_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--platform", type=str, choices=ACTIVE_PLATFORMS, default=None, help="Run specific platform (default: both)")
    parser.add_argument("--count", type=int, default=DAILY_TARGET_PER_PLATFORM, help="Daily target per platform (default: 20)")
    parser.add_argument("--stage", action="store_true", help="Pre-fill and stage only without submitting")
    parser.add_argument("--force", action="store_true", help="Apply full --count ignoring jobs already applied today")
    parser.add_argument("--phone", type=str, default=None, help="Target WhatsApp phone number")
    parser.add_argument("--no-whatsapp", action="store_true", help="Skip WhatsApp notification dispatch")
    parser.add_argument("--with-outreach", action="store_true", help="Also generate top Tier 1/3 LinkedIn outreach queue")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Autom8 Unified Job Application Pipeline (JSON-only, Zero Screenshots)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"Default (no subcommand): runs full live pipeline for {DAILY_TARGET_PER_PLATFORM} jobs per platform.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Pipeline commands")

    # pipeline
    p_pipe = subparsers.add_parser("pipeline", help="Run full daily application pipeline (default)")
    _add_pipeline_flags(p_pipe)

    # stats
    subparsers.add_parser("stats", help="Display stats from data/applied_jobs.json")

    # history
    p_hist = subparsers.add_parser("history", help="List submitted applications from data/applied_jobs.json")
    p_hist.add_argument("--platform", type=str, choices=ACTIVE_PLATFORMS, default=None)
    p_hist.add_argument("--date", type=str, default=datetime.date.today().isoformat(), help="Filter by YYYY-MM-DD (default: today)")
    p_hist.add_argument("--limit", type=int, default=40)

    # discover
    p_disc = subparsers.add_parser("discover", help="Preview fresh paid target roles without applying")
    p_disc.add_argument("--platform", type=str, choices=ACTIVE_PLATFORMS, default=None)
    p_disc.add_argument("--limit", type=int, default=15)

    # apply
    p_app = subparsers.add_parser("apply", help="Apply directly to a single job URL")
    p_app.add_argument("--url", type=str, required=True, help="Direct job application URL")
    p_app.add_argument("--company", type=str, default="Company")
    p_app.add_argument("--title", type=str, default="AI Engineer")
    p_app.add_argument("--jd", type=str, default="")
    p_app.add_argument("--stage", action="store_true", help="Pre-fill without clicking Submit")
    p_app.add_argument("--visible", action="store_true", help="Show browser window")
    p_app.add_argument("--allow-external", action="store_true", help="Allow external ATS URLs outside active platforms")

    # tailor
    p_tai = subparsers.add_parser("tailor", help="Generate tailored ATS PDF resume")
    p_tai.add_argument("--company", type=str, required=True)
    p_tai.add_argument("--title", type=str, required=True)
    p_tai.add_argument("--jd", type=str, default="")

    # outreach
    p_out = subparsers.add_parser("outreach", help="Generate LinkedIn recruiter outreach queue")
    p_out.add_argument("--limit", type=int, default=15)
    p_out.add_argument("--phone", type=str, default=None)
    p_out.add_argument("--no-whatsapp", action="store_true")

    # sync
    p_sync = subparsers.add_parser("sync", help="Sync live Internshala outcomes into data/applied_jobs.json")
    p_sync.add_argument("--pages", type=int, default=5, help="Dashboard pages to scan (10 apps/page, default: 5)")

    # login
    p_log = subparsers.add_parser("login", help="Log into platform browser profile")
    p_log.add_argument("platform", choices=["wellfound", "internshala", "whatsapp"])

    return parser


def main() -> None:
    argv = sys.argv[1:]
    # Default to `pipeline` subcommand when invoked without subcommand or directly with pipeline flags
    if not argv or (argv[0] not in SUBCOMMANDS and argv[0] not in ("-h", "--help")):
        argv = ["pipeline"] + argv

    parser = build_parser()
    args = parser.parse_args(argv)

    dispatch = {
        "pipeline": cmd_pipeline,
        "stats": cmd_stats,
        "history": cmd_history,
        "discover": cmd_discover,
        "apply": cmd_apply,
        "tailor": cmd_tailor,
        "outreach": cmd_outreach,
        "sync": cmd_sync,
        "login": cmd_login,
    }
    handler = dispatch.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
