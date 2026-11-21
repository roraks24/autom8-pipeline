#!/usr/bin/env python3
"""
send_latest_report.py - Quickly sends the most recent daily application report to WhatsApp.

Usage:
    python send_latest_report.py                      # Sends to default target in config (8854905995)
    python send_latest_report.py --phone 7877169982   # Sends to Rohit's own number ("Message yourself")
    python send_latest_report.py --phone 8854905995   # Sends to alternate number
"""

import argparse
import sys
from pathlib import Path
from whatsapp_sender import send_whatsapp, load_config, normalize_phone

BASE = Path(__file__).resolve().parent
LOGS_DIR = BASE / "application_logs"

def send_latest(phone=None):
    reports = sorted(LOGS_DIR.glob("daily_report_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not reports:
        print("No daily reports found in application_logs/.")
        return

    latest = reports[0]
    print(f"Loading latest report: {latest.name}")
    content = latest.read_text(encoding="utf-8")

    # Convert markdown table to WhatsApp friendly text
    lines = content.splitlines()
    header_info = []
    jobs = []
    parsing_jobs = False

    for line in lines:
        if line.startswith("# ") or line.startswith("**"):
            header_info.append(line.replace("**", "*"))
        elif line.startswith("| Priority Tier |") or line.startswith("| Platform |"):
            parsing_jobs = True
            continue
        elif line.startswith("| :---"):
            continue
        elif parsing_jobs and line.startswith("|"):
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if len(parts) >= 7:
                tier_str, plat, comp, role, sal, skills, act = parts[:7]
                tier_str = tier_str.replace("`", "")
                comp = comp.replace("**", "")
                skills = skills.replace("`", "")
                jobs.append({
                    "tier": tier_str,
                    "platform": plat,
                    "company": comp,
                    "role": role,
                    "salary": sal,
                    "skills": skills,
                    "action": act
                })
            elif len(parts) >= 6:
                plat, comp, role, sal, skills, act = parts[:6]
                comp = comp.replace("**", "")
                skills = skills.replace("`", "")
                jobs.append({
                    "tier": "Tier 2",
                    "platform": plat,
                    "company": comp,
                    "role": role,
                    "salary": sal,
                    "skills": skills,
                    "action": act
                })

    wa_lines = [
        "🚀 *Daily Target Roles Application Report*",
        "👤 *Candidate:* Rohit Saini",
        "🎯 *Focus:* GenAI, AI Engineer, AI Agent (Tier 1-3 Only)",
        f"📊 *Applications Count:* {len(jobs)} across 4 platforms\n"
    ]
    for idx, j in enumerate(jobs, 1):
        tier_tag = f" - 🎯 *{j['tier']}*" if j.get("tier") else ""
        wa_lines.append(
            f"*{idx}. {j['company']}* ({j['platform']}){tier_tag}\n"
            f"💼 *Role:* {j['role']}\n"
            f"💰 *Salary:* {j['salary']}\n"
            f"🛠 *Skills:* {j['skills']}\n"
            f"📌 *Action Required:* {j['action']}\n"
        )
    wa_lines.append("✅ All resumes tailored ATS-friendly with LangChain & LangGraph.")
    wa_text = "\n".join(wa_lines)

    target_phone = phone or load_config().get("preferred_target") or "8854905995"
    target_phone = normalize_phone(target_phone)
    print(f"Dispatching report to WhatsApp: +{target_phone}...")
    success = send_whatsapp(wa_text, phone=target_phone)
    if success:
        print(f"✅ Report successfully dispatched to +{target_phone}!")
    else:
        print(f"❌ Failed to dispatch report to +{target_phone}.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Send latest daily report to WhatsApp")
    parser.add_argument("--phone", type=str, default=None, help="Target phone number (e.g. 8854905995 or 7877169982)")
    args = parser.parse_args()
    send_latest(phone=args.phone)
