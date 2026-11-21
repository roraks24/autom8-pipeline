#!/usr/bin/env python3
"""
internshala_api_applier.py (Facade) - Automated direct API application engine for Internshala.

Forwards to modular package implementation in src.appliers.internshala.
"""

from src.appliers.internshala import InternshalaApplier


def main():
    import argparse
    import json
    import sqlite3
    import time
    from src.config import DB_PATH

    parser = argparse.ArgumentParser(description="Internshala Direct API Application Engine")
    parser.add_argument("--url", type=str, help="Single Internshala job URL to process")
    parser.add_argument("--batch", type=int, default=0, help="Process top N new/login_required Internshala jobs from jobs.db")
    parser.add_argument("--submit", action="store_true", help="Live submit (default is dry-run / staging)")
    parser.add_argument("--verify", action="store_true", help="Verify session and show recent applications")
    args = parser.parse_args()

    applier = InternshalaApplier()

    if args.verify:
        ok, msg = applier.verify_session()
        print(f"Session Active: {ok} ({msg})")
        apps = applier.get_recent_applications(limit=5)
        print(f"\nRecent Applications on Profile ({len(apps)}):")
        for a in apps:
            print(f"  - [{a.get('applied_at')}] {a.get('company_name')} | {a.get('profile_to_display')} | Status: {a.get('application_status')} (ID: {a.get('id')})")
        return

    mode = "submit" if args.submit else "stage"

    if args.url:
        print(f"Processing URL in {mode.upper()} mode: {args.url}")
        res = applier.apply_to_job(args.url, mode=mode)
        print(json.dumps(res, indent=2))
        return

    if args.batch > 0:
        print(f"Processing batch of {args.batch} Internshala jobs in {mode.upper()} mode...")
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "SELECT id, company, title, url FROM jobs WHERE source='internshala' AND status IN ('new', 'login_required') ORDER BY llm_score DESC, kw_score DESC LIMIT ?",
            (args.batch,)
        )
        jobs = c.fetchall()
        conn.close()

        print(f"Found {len(jobs)} candidate jobs in database.\n")
        applied_count = 0
        for jid, comp, title, url in jobs:
            print(f"> [{comp}] {title}")
            print(f"  URL: {url}")
            res = applier.apply_to_job(url, mode=mode)
            print(f"  Status: {res['status'].upper()} - {res['message']}")
            if res.get("application_id"):
                print(f"  Application ID: {res['application_id']}")
            print("-" * 50)
            if res["status"] in ("applied", "staged_for_review"):
                applied_count += 1
            time.sleep(2)

        print(f"\nCompleted! {applied_count}/{len(jobs)} jobs processed.")


if __name__ == "__main__":
    main()
