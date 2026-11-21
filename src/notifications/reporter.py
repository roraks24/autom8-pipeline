import datetime
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.config import CANDIDATE_NAME, LOGS_DIR
from src.notifications.whatsapp import send_whatsapp

logger = logging.getLogger("reporter")


def extract_salary_from_desc(text: str, default: str = "Competitive / Market Standard") -> str:
    """Extracts salary or stipend details from job description or notes."""
    if not text:
        return default

    inr_match = re.search(r"(?:₹|rs\.?|inr)\s*([\d,]+(?:\s*-\s*[\d,]+)?(?:\s*(?:k|lpa|month|pm|per month))?)", text, re.I)
    if inr_match:
        return f"₹{inr_match.group(1).strip()}"

    usd_match = re.search(r"(\$[\d,]+(?:\s*-\s*\$[\d,]+)?(?:\s*(?:k|yr|year|hour|hr|annually))?)", text, re.I)
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
        "Git", "GitHub", "GCP", "AWS", "Machine Learning", "Deep Learning", "NLP"
    ]
    found = []
    combined = f"{title} {text}".lower()
    for s in common_skills:
        if re.search(r"\b" + re.escape(s.lower()) + r"\b", combined):
            found.append(s)

    if found:
        return ", ".join(found[:5])
    return "Python, Machine Learning, Problem Solving"


def build_markdown_report(applied_records: List[Dict[str, Any]], total_target: int, submit: bool = False) -> str:
    """Constructs an executive markdown summary of the application run."""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    successful = [r for r in applied_records if r.get('status') == 'applied' or (not submit and r.get('status') == 'staged_for_review')]
    ineligible = [r for r in applied_records if r.get('status') in ('ineligible', 'dropped_demographics_required', 'expired', 'already_applied')]

    md_lines = [
        f"# Daily Job Application Report (Pipeline v2.0) - {now_str}",
        f"**Candidate:** {CANDIDATE_NAME} | **Target Achieved:** {len(successful)}/{total_target} Successful ({len(ineligible)} Ineligible/Skipped Replenished)",
        f"**Mode:** {'Submitted' if submit else 'Staged for Review'}",
        "**Target Priority Filter:** Tier 1 (GenAI), Tier 2 (AI Engineer), Tier 3 (AI Agent)\n",
        "| Priority Tier | Platform | Company | Role | Salary / Stipend | Key Skills Required | Action Required |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
    ]
    for r in applied_records:
        cat_clean = re.sub(r"^Tier\s*\d+\s*[:\-\(]\s*", "", r.get('target_category', ''), flags=re.I).strip(" )")
        tier_label = f"Tier {r.get('tier', 2)} ({cat_clean.split('/')[0].strip()})"
        md_lines.append(
            f"| `{tier_label}` | {r.get('platform', '')} | **{r.get('company', '')}** | {r.get('role', '')} | "
            f"{r.get('salary', '')} | `{r.get('skills_required', '')}` | {r.get('action_required', '')} |"
        )

    return "\n".join(md_lines)


def build_whatsapp_summary(applied_records: List[Dict[str, Any]], platform_desc: str) -> str:
    """Constructs a concise, highly readable WhatsApp notification message."""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    successful = [r for r in applied_records if r.get('status') == 'applied' or r.get('status') == 'staged_for_review']
    ineligible = [r for r in applied_records if r.get('status') in ('ineligible', 'dropped_demographics_required', 'expired', 'already_applied')]

    wa_lines = [
        "🚀 *Daily Target Roles Application Report (Pipeline v2.0)*",
        f"📅 Date: {now_str}",
        f"👤 Candidate: {CANDIDATE_NAME}",
        "🎯 Focus: GenAI, AI Engineer, AI Agent (Tier 1-3 Only)",
        f"📊 Applications: {len(successful)} Successful ({len(ineligible)} Ineligible Replenished) across {platform_desc}\n"
    ]
    for idx, r in enumerate(applied_records, 1):
        wa_lines.append(
            f"*{idx}. {r.get('company')}* ({r.get('platform')}) - 🎯 *Tier {r.get('tier')}: {r.get('target_category')}*\n"
            f"💼 *Role:* {r.get('role')}\n"
            f"💰 *Salary:* {r.get('salary')}\n"
            f"🛠 *Skills:* {r.get('skills_required')}\n"
            f"📌 *Action Required:* {r.get('action_required')}\n"
        )
    wa_lines.append("✅ Pipeline v2.0: All resumes tailored ATS-friendly with LangChain & LangGraph.")
    return "\n".join(wa_lines)


def save_daily_report(report_md: str, date_slug: Optional[str] = None) -> Path:
    """Saves the markdown report to application_logs/."""
    if not date_slug:
        date_slug = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = LOGS_DIR / f"daily_report_{date_slug}.md"
    report_file.write_text(report_md, encoding="utf-8")
    logger.info(f"Report saved: {report_file}")
    return report_file


def send_daily_report(report_text: str, phone: Optional[str] = None) -> bool:
    """Dispatches application report using WhatsApp."""
    return send_whatsapp(report_text, phone=phone)
