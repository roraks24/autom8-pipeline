#!/usr/bin/env python3
"""
apply_bot.py (Pipeline v2.0 Facade) - Step 3 of the job application automation pipeline.

Forwards to modular package implementation in src/:
- src.appliers.router: Master multi-platform dispatcher
- src.appliers.ats: Ashby, Lever, Greenhouse
- src.appliers.wellfound: Wellfound v2.0
- src.appliers.internshala: Internshala REST API & modal applier
- src.appliers.wwr: We Work Remotely
- src.appliers.naukri: Naukri
- src.core.tailor: Dynamic ATS resume generation
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict

from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from src.config import (
    ACTIVE_PLATFORMS,
    ANSWER_BANK_PATH,
    BASE_DIR,
    DB_PATH,
    LOGS_DIR,
    RESUMES_DIR,
    load_answer_bank,
)
from src.core.tailor import get_or_create_resume
from src.core.workflow import human_delay
from src.appliers.ats import fill_ashby_form, fill_greenhouse_form, fill_lever_form
from src.appliers.internshala import fill_internshala_form
from src.appliers.wellfound import fill_wellfound_form
from src.appliers.router import apply_to_job


def main():
    parser = argparse.ArgumentParser(description="Automate job applications (Pipeline v2.0)")
    parser.add_argument("--url", help="Direct job application URL")
    parser.add_argument("--job-id", help="Job ID from jobs.db")
    parser.add_argument("--company", default="Company", help="Company name")
    parser.add_argument("--title", default="AI Engineer", help="Job title")
    parser.add_argument("--submit", action="store_true", help="Auto-click submit button (default is pre-fill and review)")
    parser.add_argument("--batch", type=int, help="Stage applications for top N new jobs from jobs.db")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--login-internshala", action="store_true", help="Open visible Chrome window to log into Internshala once")
    parser.add_argument("--login-wellfound", action="store_true", help="Open visible Chrome window to log into Wellfound once")
    parser.add_argument("--login-creds", nargs=2, metavar=("EMAIL", "PASSWORD"), help="Log into Internshala headlessly using email and password")
    args = parser.parse_args()

    if args.login_creds:
        email, password = args.login_creds
        profile_dir = Path.home() / ".chrome_job_profile"
        print(f"\nLogging into Internshala headlessly for {email}...", flush=True)
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=True,
                viewport={"width": 1280, "height": 900}
            )
            page = ctx.new_page()
            page.goto("https://internshala.com/login/student", timeout=25000)
            page.wait_for_timeout(1000)
            page.fill("input#email", email)
            page.fill("input#password", password)
            page.click("button#login_submit")
            page.wait_for_timeout(4000)
            page.screenshot(path=str(LOGS_DIR / "login_result.png"))
            content = page.content().lower()
            if "dashboard" in page.url or "student/dashboard" in page.url or "my_applications" in content:
                print("✅ Successfully logged into Internshala! Session saved to profile.", flush=True)
            else:
                print(f"Current page URL: {page.url}", flush=True)
                print("Proof screenshot saved to application_logs/login_result.png", flush=True)
            ctx.close()
        return

    if args.login_internshala:
        from main import cmd_login
        class LoginArgs:
            platform = "internshala"
        cmd_login(LoginArgs())
        return

    if args.login_wellfound:
        from main import cmd_login
        class LoginArgs:
            platform = "wellfound"
        cmd_login(LoginArgs())
        return

    if args.batch:
        if not DB_PATH.exists():
            sys.exit("jobs.db not found. Run job_discovery.py first.")
        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        placeholders = ",".join("?" for _ in ACTIVE_PLATFORMS)
        rows = con.execute(
            f"SELECT id, company, title, url, notes FROM jobs WHERE status IN ('new', 'login_required') AND source IN ({placeholders}) ORDER BY llm_score DESC, kw_score DESC LIMIT ?",
            (*ACTIVE_PLATFORMS, args.batch)
        ).fetchall()
        con.close()
        if not rows:
            print(f"No new jobs from {', '.join(p.capitalize() for p in ACTIVE_PLATFORMS)} to apply to in jobs.db.")
            return
        print(f"Staging applications for top {len(rows)} jobs ({', '.join(p.capitalize() for p in ACTIVE_PLATFORMS)})...")
        for idx, r in enumerate(rows, 1):
            apply_to_job(r["url"], company=r["company"], title=r["title"], notes=r["notes"] or "", submit=args.submit, headless=args.headless)
            if idx < len(rows):
                human_delay(context=f"Batch #{idx}/{len(rows)}")
        return

    target_url = args.url
    comp = args.company
    title = args.title
    notes = ""

    if args.job_id:
        if not DB_PATH.exists():
            sys.exit("jobs.db not found.")
        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT company, title, url, notes FROM jobs WHERE id=?", (args.job_id,)).fetchone()
        con.close()
        if not row:
            sys.exit(f"Job {args.job_id} not found in jobs.db.")
        comp, title, target_url, notes = row["company"], row["title"], row["url"], row["notes"] or ""

    if not target_url:
        sys.exit("Provide either --url or --job-id or --batch.")

    apply_to_job(target_url, company=comp, title=title, notes=notes, submit=args.submit, headless=args.headless)


if __name__ == "__main__":
    main()
