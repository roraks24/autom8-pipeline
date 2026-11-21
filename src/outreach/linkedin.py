import datetime
import json
import logging
import sqlite3
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.config import (
    CANDIDATE_EMAIL,
    CANDIDATE_NAME,
    DB_PATH,
    DEFAULT_PHONE,
    GITHUB_URL,
    LOGS_DIR,
    PORTFOLIO_URL,
)
from src.notifications.whatsapp import load_config, normalize_phone, send_whatsapp

logger = logging.getLogger("outreach")


def generate_outreach_targets(limit: int = 15) -> List[Dict[str, Any]]:
    """Fetches high-priority applied companies from jobs.db and generates tailored outreach."""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    rows = con.execute("""
        SELECT company, title, source, url, target_tier, target_category, notes
        FROM jobs
        WHERE status IN ('applied', 'staged_for_review')
          AND target_tier IN (1, 2, 3)
          AND company NOT IN ('Startup', 'Unknown', 'Company')
        GROUP BY company
        ORDER BY 
            target_tier ASC,
            id DESC
        LIMIT ?
    """, (limit,)).fetchall()
    con.close()

    targets = []
    for r in rows:
        comp = r["company"].strip()
        role = r["title"].strip()
        tier = r["target_tier"]
        cat = r["target_category"] or "AI Engineering"

        # Search links
        google_query = f'site:linkedin.com/in/ "{comp}" ("technical recruiter" OR "talent acquisition" OR "engineering manager" OR "founder" OR "head of ai")'
        google_search_url = f"https://www.google.com/search?q={urllib.parse.quote(google_query)}"
        linkedin_search_url = f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote(comp + ' recruiter')}"

        # 300-character connection note (strictly <= 300 chars)
        if tier == 1:
            note = f"Hi! Applied for the {role} role at {comp}. Built Rorak AI (live RAG on FastAPI/Cloud Run at rorak.tech) and multi-agent workflows for NVIDIA's AI hackathon. Would love to connect and follow {comp}'s GenAI progress!"
        elif tier == 3:
            note = f"Hi! Applied for the {role} at {comp}. Built a 5-agent stateful workflow for NVIDIA's Agentic AI Hackathon & Rorak AI (FastAPI/Cloud Run at rorak.tech). Would love to connect and follow {comp}'s agentic engineering!"
        else:
            note = f"Hi! Applied for the {role} role at {comp}. I specialize in Python, FastAPI, and deploying LLM/RAG systems (built Rorak AI at rorak.tech, ISRO BAH finalist). Would love to connect and follow your engineering work at {comp}!"

        if len(note) > 300:
            note = note[:297] + "..."

        # Full follow-up DM (once connection is accepted)
        dm = (
            f"Hi [Name], thanks for connecting!\n\n"
            f"I recently submitted my application for the {role} position at {comp}. "
            f"Given {comp}'s focus in {cat.split('/')[0].strip()}, I wanted to briefly highlight my hands-on background:\n\n"
            f"• Rorak AI (Production RAG): Containerized FastAPI backend on Google Cloud Run with FAISS vector search and Groq Llama 3.3 (live at {PORTFOLIO_URL})\n"
            f"• Multi-Agent Systems: Designed a 5-agent collaborative scoping architecture for NVIDIA's Agentic AI Hackathon\n"
            f"• Backend Engineering: Clean Python/FastAPI APIs with pytest, Docker, and CI/CD pipelines\n\n"
            f"I've attached my tailored resume and would love the opportunity for a brief introductory call. "
            f"Looking forward to hearing your thoughts!\n\n"
            f"Best regards,\n"
            f"{CANDIDATE_NAME} | {CANDIDATE_EMAIL} | +{DEFAULT_PHONE}\n"
            f"Portfolio: {PORTFOLIO_URL} | GitHub: {GITHUB_URL}"
        )

        targets.append({
            "company": comp,
            "role": role,
            "tier": tier,
            "category": cat,
            "google_search": google_search_url,
            "linkedin_search": linkedin_search_url,
            "connection_note": note,
            "note_len": len(note),
            "followup_dm": dm
        })

    return targets


def build_markdown_report(targets: List[Dict[str, Any]]) -> str:
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# LinkedIn Recruiter & Founder Outreach Queue - {now_str}",
        f"**Candidate:** {CANDIDATE_NAME} | **Priority Targets:** {len(targets)} Companies",
        "**Safety:** 100% Account Safe (0% Ban Risk — Human-in-the-loop 1-Click Dispatch)\n",
        "---"
    ]

    for idx, t in enumerate(targets, 1):
        tier_badge = f"Tier {t['tier']} ({t['category'].split('/')[0].strip()})"
        lines.append(f"### {idx}. {t['company']} — {t['role']} (`{tier_badge}`)")
        lines.append(f"- 🔍 **Find Recruiters/Founders:** [Google Search]({t['google_search']}) | [LinkedIn Search]({t['linkedin_search']})")
        lines.append(f"- ✉️ **300-Char Connection Note** ({t['note_len']}/300 chars):")
        lines.append(f"  > ```text\n  > {t['connection_note']}\n  > ```")
        lines.append(f"- 💬 **Follow-Up InMail / DM:**")
        lines.append(f"  ```text\n{t['followup_dm']}\n  ```")
        lines.append("---\n")

    return "\n".join(lines)


def build_html_dashboard(targets: List[Dict[str, Any]]) -> str:
    """Builds a beautiful 1-click copy HTML dashboard for rapid outreach."""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    html_cards = []

    for idx, t in enumerate(targets, 1):
        tier_color = "#3b82f6" if t['tier'] == 1 else "#10b981" if t['tier'] == 2 else "#8b5cf6"

        card = f"""
        <div class="card">
            <div class="card-header">
                <span class="badge" style="background-color: {tier_color};">Tier {t['tier']}</span>
                <h3>{idx}. {t['company']}</h3>
                <span class="role">{t['role']}</span>
            </div>
            <div class="links">
                <a href="{t['google_search']}" target="_blank" class="btn btn-search">🔍 Google Recruiter Search</a>
                <a href="{t['linkedin_search']}" target="_blank" class="btn btn-linkedin">💼 LinkedIn People Search</a>
            </div>
            <div class="section-title">Connection Invite Note ({t['note_len']}/300 chars)</div>
            <div class="note-box" id="note-{idx}">{t['connection_note']}</div>
            <button class="btn btn-copy" onclick="copyText('note-{idx}')">📋 Copy Connection Note</button>

            <div class="section-title" style="margin-top: 15px;">Follow-Up DM / InMail</div>
            <textarea class="dm-box" id="dm-{idx}" readonly>{t['followup_dm']}</textarea>
            <button class="btn btn-copy" onclick="copyText('dm-{idx}')">📋 Copy Follow-Up DM</button>
        </div>
        """
        html_cards.append(card)

    cards_html = "\n".join(html_cards)

    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>LinkedIn Outreach Queue - {CANDIDATE_NAME}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background: #0f172a;
            color: #f8fafc;
            margin: 0;
            padding: 24px;
        }}
        .header {{
            text-align: center;
            margin-bottom: 24px;
        }}
        .header h1 {{ margin-bottom: 6px; font-size: 26px; }}
        .header p {{ color: #94a3b8; font-size: 14px; margin-top: 0; }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(450px, 1fr));
            gap: 20px;
            max-width: 1400px;
            margin: 0 auto;
        }}
        .card {{
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 12px;
            padding: 18px;
            display: flex;
            flex-direction: column;
        }}
        .card-header {{
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 12px;
            flex-wrap: wrap;
        }}
        .badge {{
            padding: 4px 8px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: bold;
            text-transform: uppercase;
        }}
        .card-header h3 {{ margin: 0; font-size: 18px; color: #f1f5f9; }}
        .role {{ color: #38bdf8; font-size: 13px; font-weight: 500; width: 100%; margin-top: 2px; }}
        .links {{ display: flex; gap: 8px; margin-bottom: 14px; }}
        .btn {{
            display: inline-block;
            padding: 6px 12px;
            font-size: 12px;
            border-radius: 6px;
            text-decoration: none;
            cursor: pointer;
            border: none;
            font-weight: 500;
            transition: all 0.2s ease;
        }}
        .btn-search {{ background: #0284c7; color: white; }}
        .btn-linkedin {{ background: #0a66c2; color: white; }}
        .btn-copy {{ background: #475569; color: white; margin-top: 6px; }}
        .btn-copy:hover {{ background: #64748b; }}
        .section-title {{ font-size: 12px; color: #94a3b8; font-weight: 600; text-transform: uppercase; margin-bottom: 4px; }}
        .note-box {{
            background: #0f172a;
            border: 1px solid #334155;
            border-radius: 6px;
            padding: 10px;
            font-size: 13px;
            line-height: 1.4;
            color: #e2e8f0;
        }}
        .dm-box {{
            background: #0f172a;
            border: 1px solid #334155;
            border-radius: 6px;
            padding: 10px;
            font-size: 12px;
            line-height: 1.4;
            color: #cbd5e1;
            height: 110px;
            resize: vertical;
            font-family: inherit;
        }}
    </style>
    <script>
        function copyText(id) {{
            const el = document.getElementById(id);
            const val = el.value !== undefined ? el.value : el.innerText;
            navigator.clipboard.writeText(val).then(() => {{
                alert("Copied to clipboard!");
            }});
        }}
    </script>
</head>
<body>
    <div class="header">
        <h1>🎯 LinkedIn Recruiter & Founder Outreach Queue</h1>
        <p>{CANDIDATE_NAME} | 100% Account Safe (0% Ban Risk) | {now_str}</p>
    </div>
    <div class="grid">
        {cards_html}
    </div>
</body>
</html>
"""
    return full_html


def run_linkedin_outreach(limit: int = 15, phone: Optional[str] = None) -> Tuple[List[Dict[str, Any]], Path, Path]:
    """Generates outreach targets, creates dashboard and markdown files, and sends WhatsApp alert."""
    print("=" * 65)
    print("      LINKEDIN RECRUITER & FOUNDER OUTREACH GENERATOR")
    print(f"      Candidate: {CANDIDATE_NAME} (+{DEFAULT_PHONE})")
    print("      Safety: 100% Account Safe (Human-in-the-Loop Dispatch)")
    print("=" * 65)

    targets = generate_outreach_targets(limit=limit)
    print(f"Generated outreach packages for {len(targets)} applied companies.\n")

    date_slug = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    md_content = build_markdown_report(targets)
    md_path = LOGS_DIR / f"linkedin_outreach_{date_slug}.md"
    md_path.write_text(md_content, encoding="utf-8")
    print(f"✅ Markdown Queue Saved: {md_path.name}")

    html_content = build_html_dashboard(targets)
    html_path = LOGS_DIR / f"linkedin_outreach_{date_slug}.html"
    html_path.write_text(html_content, encoding="utf-8")
    print(f"✅ Interactive HTML Dashboard Saved: {html_path.name}")

    cfg = load_config()
    target_phone = phone or cfg.get("preferred_target") or DEFAULT_PHONE
    target_phone = normalize_phone(target_phone)

    wa_lines = [
        "🎯 *Top LinkedIn Recruiter Outreach Queue*",
        f"👤 Candidate: {CANDIDATE_NAME}",
        "🛡️ 100% Safe: 0% Ban Risk (Send manually from your browser)\n"
    ]
    for idx, t in enumerate(targets[:5], 1):
        wa_lines.append(
            f"*{idx}. {t['company']}* ({t['role']})\n"
            f"🔍 Find Recruiter: {t['linkedin_search']}\n"
            f"✉️ *Connection Note ({t['note_len']}/300 chars):*\n"
            f"\"{t['connection_note']}\"\n"
        )
    wa_lines.append(f"📊 Full dashboard with all {len(targets)} targets saved to:\n`{html_path.name}`")
    wa_text = "\n".join(wa_lines)

    print(f"\nSending top 5 targets to WhatsApp (+{target_phone})...")
    send_whatsapp(wa_text, phone=target_phone)
    print("Done!")

    return targets, md_path, html_path


def main():
    import argparse
    parser = argparse.ArgumentParser(description="LinkedIn Recruiter & Founder Outreach Generator")
    parser.add_argument("--limit", type=int, default=15, help="Number of companies to generate outreach for")
    parser.add_argument("--phone", type=str, default=None, help="Target WhatsApp phone number")
    args = parser.parse_args()

    run_linkedin_outreach(limit=args.limit, phone=args.phone)


if __name__ == "__main__":
    main()
