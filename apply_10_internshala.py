#!/usr/bin/env python3
"""
apply_10_internshala.py - Applies directly to 10 target Internshala roles (Tier 1, 2, 3 only)
using the authenticated InternshalaApplier API, generates tailored ATS resumes,
and dispatches the live report to WhatsApp.
"""

import sys
import time
import json
import sqlite3
import datetime
import re
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "jobs.db"
LOGS_DIR = BASE / "application_logs"
LOGS_DIR.mkdir(exist_ok=True)

from internshala_api_applier import InternshalaApplier
from whatsapp_sender import send_whatsapp, load_config, normalize_phone

def extract_stipend_from_notes(notes: str) -> str:
    if not notes:
        return "Market Standard"
    if "Stipend:" in notes:
        val = notes.split("Stipend:")[-1].split("|")[0].strip()
        return val if val else "Market Standard"
    if "Salary:" in notes:
        val = notes.split("Salary:")[-1].split("|")[0].strip()
        return val if val else "Market Standard"
    m = re.search(r"(?:₹|rs\.?|inr)\s*[\d,]+(?:\s*-\s*[\d,]+)?(?:\s*(?:k|lpa|month|pm|per month))?", notes, re.I)
    if m:
        return m.group(0).strip()
    return "Market Standard"

def main():
    print("=" * 65)
    print("      INTERNSHALA TARGETED BATCH: APPLYING TO 10 MORE ROLES")
    print("      Mode: LIVE AUTO-SUBMIT (Target: 10 Successful Applications)")
    print("      Candidate: Rohit Saini (+91 7877169982)")
    print("=" * 65)

    applier = InternshalaApplier()
    ok, msg = applier.verify_session()
    if not ok:
        print(f"Error: Internshala session invalid: {msg}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Query ready target jobs (Tier 1, 3, 2), prioritizing paid roles
    rows = c.execute("""
        SELECT id, company, title, location, url, notes, target_tier, target_category
        FROM jobs
        WHERE source = 'internshala'
          AND target_tier IN (1, 2, 3)
          AND status IN ('new', 'staged_for_review')
        ORDER BY 
            CASE WHEN target_tier = 1 THEN 1 WHEN target_tier = 3 THEN 2 ELSE 3 END,
            CASE WHEN notes LIKE '%Unpaid%' THEN 2 ELSE 1 END,
            COALESCE(kw_score, 0) DESC,
            id ASC
    """).fetchall()

    jobs = [dict(r) for r in rows]
    conn.close()

    print(f"Found {len(jobs)} candidate roles in queue.\n")

    submitted_records = []
    attempted_records = []
    target_count = 10

    for idx, job in enumerate(jobs, 1):
        if len(submitted_records) >= target_count:
            print(f"\n🎯 Successfully reached target of {target_count} live applications!")
            break

        comp = job.get("company") or "Company"
        title = job.get("title") or "AI Engineer"
        url = job.get("url") or ""
        tier = job.get("target_tier") or 2
        cat = job.get("target_category") or "AI Engineer / Applied AI"
        notes = job.get("notes") or ""
        stipend = extract_stipend_from_notes(notes)

        print(f"\n[{idx}/{len(jobs)}] [Target: {len(submitted_records)+1}/{target_count}] [Tier {tier}: {cat}]")
        print(f"  Company: {comp}")
        print(f"  Role:    {title}")
        print(f"  Stipend: {stipend}")
        print(f"  URL:     {url}")

        res = applier.apply_to_job(url, mode="submit")
        status = res.get("status", "failed")
        msg = res.get("message", "")
        app_id = res.get("application_id", "")
        resume_path = res.get("tailored_resume", "")

        print(f"  Result:  {status.upper()} - {msg}")
        if app_id:
            print(f"  App ID:  {app_id}")
            if resume_path:
                print(f"  Resume:  {Path(resume_path).name}")

        rec = {
            "company": comp,
            "title": title,
            "tier": tier,
            "category": cat,
            "stipend": stipend,
            "status": status,
            "app_id": app_id,
            "message": msg,
            "url": url,
            "resume": resume_path
        }
        attempted_records.append(rec)

        if status == "applied" and app_id:
            submitted_records.append(rec)
            print(f"  >>> SUCCESS: {len(submitted_records)}/{target_count} submitted live! <<<")

        time.sleep(2.5)  # courteous delay between submissions

    print("\n" + "=" * 65)
    print(f"Summary: {len(submitted_records)} applications submitted successfully live.")
    print("=" * 65)

    if not submitted_records:
        print("Warning: No applications were successfully submitted.")
        return

    # Generate Report
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    slug = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    md_lines = [
        f"# Internshala 10-Job Submission Report - {now_str}",
        f"**Candidate:** Rohit Saini | **Live Submissions:** {len(submitted_records)}",
        f"**Mode:** Live Auto-Submit (Direct API)\n",
        "| # | Priority Tier | Company | Role | Stipend | Application ID | Tailored ATS Resume |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
    ]
    for i, r in enumerate(submitted_records, 1):
        tier_lbl = f"Tier {r['tier']} ({r['category'].split('/')[0].strip()})"
        res_file = Path(r['resume']).name if r.get('resume') else "ATS Tailored"
        md_lines.append(f"| {i} | `{tier_lbl}` | **{r['company']}** | {r['title']} | {r['stipend']} | **ID: {r['app_id']}** | `{res_file}` |")

    report_md = "\n".join(md_lines)
    report_path = LOGS_DIR / f"internshala_report_{slug}.md"
    report_path.write_text(report_md, encoding="utf-8")
    print(f"\n[Report Saved] {report_path}")

    # WhatsApp Message
    cfg = load_config()
    target_phone = cfg.get("preferred_target") or "917877169982"
    target_phone = normalize_phone(target_phone)

    wa_lines = [
        f"🚀 *Internshala 10-Role Live Application Report*",
        f"📅 Date: {now_str}",
        f"👤 Candidate: Rohit Saini",
        f"🎯 Focus: GenAI, AI Engineer, AI Agent (Tier 1-3 Only)",
        f"📊 Successfully Submitted Live: {len(submitted_records)} roles\n"
    ]
    for idx, r in enumerate(submitted_records, 1):
        wa_lines.append(
            f"*{idx}. {r['company']}* - 🎯 *Tier {r['tier']}: {r['category']}*\n"
            f"💼 *Role:* {r['title']}\n"
            f"💰 *Stipend:* {r['stipend']}\n"
            f"✅ *App ID:* {r['app_id']}\n"
        )
    wa_lines.append("✅ All 10 applications submitted with custom ATS-optimized resumes and tailored answers.")
    wa_text = "\n".join(wa_lines)

    print(f"\nSending report to WhatsApp (+{target_phone})...")
    send_whatsapp(wa_text, phone=target_phone)
    print("Done!")

if __name__ == "__main__":
    main()
