#!/usr/bin/env python3
"""
daily_workflow.py (Pipeline v2.0 Facade) - Master daily job application workflow.

Forwards to modular package implementation in src/:
- src.core.workflow: Pipeline execution and orchestration
- src.db.repository: SQLite storage and priority sorting
- src.notifications: WhatsApp and executive report generation
"""

import argparse
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from src.config import BASE_DIR, DB_PATH, LOGS_DIR
from src.core.workflow import run_daily_workflow
from src.db.repository import get_platform_jobs
from src.notifications.reporter import (
    extract_salary_from_desc,
    extract_skills_from_desc,
    send_daily_report as send_whatsapp_report,
)
from src.notifications.whatsapp import load_config, normalize_phone, send_whatsapp


def main():
    parser = argparse.ArgumentParser(description="Run daily job application workflow (Pipeline v2.0)")
    parser.add_argument("--platform", type=str, default=None, help="Specific platform to run (default: wellfound, internshala)")
    parser.add_argument("--submit", action="store_true", help="Auto-submit applications (default is stage & review)")
    parser.add_argument("--count", type=int, default=20, help="Number of jobs per platform (default: 20)")
    parser.add_argument("--phone", type=str, default=None, help="Target WhatsApp phone number (default: from config)")
    args = parser.parse_args()

    run_daily_workflow(submit=args.submit, jobs_per_platform=args.count, phone=args.phone, platform=args.platform)


if __name__ == "__main__":
    main()
