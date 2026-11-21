#!/usr/bin/env python3
"""
run_pipeline.py - Master Orchestrator for the Job Application Automation Pipeline.

Runs the full end-to-end cycle:
  1. Discovery & Deduplication (Greenhouse, Lever, Ashby, WWR, Himalayas -> jobs.db)
  2. ATS Tailoring & PDF Generation (tailor.py -> tailored_resumes/)
  3. Form Automation & Staging (apply_bot.py -> application_logs/ + jobs.db)

Usage:
    python run_pipeline.py             # Run discovery + tailor + stage top 3 jobs for review
    python run_pipeline.py --auto-submit  # Auto-submit directly
    python run_pipeline.py --jobs 5       # Process top 5 jobs
"""
import argparse
import os
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

# Force UTF-8 on Windows stdout/stderr
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE = Path(__file__).resolve().parent
PYTHON = sys.executable


def run_cmd(cmd, desc):
    print(f"\n{'='*60}")
    print(f"▶ Step: {desc}")
    print(f"  Command: {' '.join(cmd)}")
    print(f"{'='*60}", flush=True)
    t0 = time.time()
    proc = subprocess.Popen(
        cmd,
        cwd=str(BASE),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace"
    )
    for line in iter(proc.stdout.readline, ""):
        print(line, end="", flush=True)
    proc.stdout.close()
    returncode = proc.wait()
    print(f"\n  Finished in {time.time() - t0:.1f}s (Exit code: {returncode})", flush=True)
    return returncode == 0


def main():
    parser = argparse.ArgumentParser(description="Master Job Hunt Automation Pipeline")
    parser.add_argument("--jobs", type=int, default=3, help="How many top jobs to stage/apply (default 3)")
    parser.add_argument("--auto-submit", action="store_true", help="Auto-click submit on forms (default is stage & screenshot)")
    parser.add_argument("--skip-discovery", action="store_true", help="Skip discovery and use existing jobs in jobs.db")
    args = parser.parse_args()

    print("\n" + "#"*60)
    print("🚀 STARTING AUTOMATED JOB APPLICATION PIPELINE")
    print(f"📅 Date: {date.today().isoformat()}")
    print(f"🎯 Target Jobs: Top {args.jobs}")
    print(f"⚙️  Mode: {'AUTO-SUBMIT' if args.auto_submit else 'PRE-FILL, STAGE & SCREENSHOT'}")
    print("#"*60)

    # Step 1: Discovery
    if not args.skip_discovery:
        ok = run_cmd([PYTHON, "job_discovery.py", "run"], "1. Job Discovery & Deduplication")
        if not ok:
            print("  ! Discovery had warnings, continuing with available jobs.")
    else:
        print("\n⏩ Skipping discovery, using existing jobs in jobs.db.")

    # Step 2: Tailoring
    run_cmd([PYTHON, "tailor.py", "--latest"], "2. Resume Tailoring & ATS PDF Compilation")

    # Step 3: Application & Form Filling
    apply_cmd = [PYTHON, "apply_bot.py", "--batch", str(args.jobs), "--headless"]
    if args.auto_submit:
        apply_cmd.append("--submit")

    run_cmd(apply_cmd, "3. Form Filling & Application Staging")

    print("\n" + "#"*60)
    print("✅ PIPELINE EXECUTION COMPLETE")
    print(f"📁 Tailored Resumes: {BASE / 'tailored_resumes'}")
    print(f"📸 Proof Screenshots: {BASE / 'application_logs'}")
    print(f"📊 Application Database: {BASE / 'jobs.db'}")
    print("#"*60 + "\n")


if __name__ == "__main__":
    main()
