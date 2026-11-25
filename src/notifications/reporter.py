import datetime
import logging
import re
from typing import Any, Dict, List, Optional

from src.config import CANDIDATE_NAME
from src.notifications.whatsapp import send_whatsapp

logger = logging.getLogger("reporter")


def extract_salary_from_desc(text: str, default: str = "Competitive / Market Standard") -> str:
    """Extracts salary or stipend details from job description or notes."""
    if not text:
        return default

    inr_match = re.search(
        r"(?:₹|rs\.?|inr)\s*([\d,]+(?:\s*-\s*[\d,]+)?(?:\s*(?:k|lpa|month|mo|pm|year|yr|per month))?)",
        text,
        re.I,
    )
    if inr_match:
        return f"₹{inr_match.group(1).strip()}"

    usd_match = re.search(
        r"(\$[\d,]+(?:\s*[–\-]\s*\$?[\d,]+)?(?:\s*(?:k|yr|year|hour|hr|annually))?)",
        text,
        re.I,
    )
    if usd_match:
        return usd_match.group(1).strip()

    lpa_match = re.search(r"(\d+(?:\.\d+)?\s*(?:-\s*\d+(?:\.\d+)?)?\s*LPA)", text, re.I)
    if lpa_match:
        return lpa_match.group(1).strip()

    return default


def extract_skills_from_desc(text: str, title: str) -> str:
    """Extracts top technical skills stated in JD."""
    common_skills = [
        "Python", "FastAPI", "Flask", "Django", "LangChain", "LangGraph", "Docker",
        "RAG", "FAISS", "Vector Search", "Groq", "OpenAI", "PyTorch", "TensorFlow",
        "scikit-learn", "Pandas", "NumPy", "PostgreSQL", "MySQL", "REST APIs",
        "Git", "GitHub", "GCP", "AWS", "Machine Learning", "Deep Learning", "NLP",
        "React", "Next.js", "Node.js", "Flutter",
    ]
    combined = f"{title} {text}".lower()
    found = [s for s in common_skills if re.search(r"\b" + re.escape(s.lower()) + r"\b", combined)]
    return ", ".join(found[:5]) if found else "Python, FastAPI, AI Engineering"


def build_whatsapp_summary(applied_records: List[Dict[str, Any]], platform_desc: str) -> str:
    """Constructs a concise WhatsApp notification summary from run records (JSON-backed, no .md files)."""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    successful = [r for r in applied_records if r.get("status") == "applied"]
    skipped = [r for r in applied_records if r.get("status") != "applied"]

    wa_lines = [
        "🚀 *Daily Target Roles Application Report*",
        f"📅 Date: {now_str}",
        f"👤 Candidate: {CANDIDATE_NAME}",
        "💾 Store: data/applied_jobs.json (JSON-only)",
        f"📊 Submitted: {len(successful)} Successful ({len(skipped)} Skipped/Replenished) across {platform_desc}\n",
    ]
    for idx, r in enumerate(successful, 1):
        app_id_note = f" | ID: {r['application_id']}" if r.get("application_id") else ""
        wa_lines.append(
            f"*{idx}. {r.get('company')}* ({r.get('platform')}{app_id_note})\n"
            f"💼 *Role:* {r.get('role')}\n"
            f"💰 *Salary:* {r.get('salary')}\n"
            f"🛠 *Skills:* {r.get('skills_required')}\n"
        )
    wa_lines.append("✅ Resumes tailored dynamically. All applied jobs saved to data/applied_jobs.json.")
    return "\n".join(wa_lines)


def print_console_summary(applied_records: List[Dict[str, Any]], db_path: str) -> None:
    """Prints a clean ASCII summary table to stdout (no markdown/screenshot files written)."""
    successful = [r for r in applied_records if r.get("status") == "applied"]
    print("\n" + "=" * 72)
    print(f"  PIPELINE EXECUTION SUMMARY — {len(successful)} Applied")
    print(f"  JSON Database: {db_path}")
    print("=" * 72)
    for idx, r in enumerate(successful, 1):
        aid = f" [ID: {r['application_id']}]" if r.get("application_id") else ""
        print(f"  {idx:>2}. [{r.get('platform')}] {r.get('company')} — {r.get('role')} ({r.get('salary')}){aid}")
    print("=" * 72)


def send_daily_report(report_text: str, phone: Optional[str] = None) -> bool:
    """Dispatches application report using WhatsApp."""
    return send_whatsapp(report_text, phone=phone)
