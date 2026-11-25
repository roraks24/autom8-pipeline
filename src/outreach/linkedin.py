import datetime
import logging
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.config import (
    CANDIDATE_EMAIL,
    CANDIDATE_NAME,
    DEFAULT_PHONE,
    GITHUB_URL,
    PORTFOLIO_URL,
)
from src.core.classifier import is_excluded_company
from src.notifications.whatsapp import load_config, normalize_phone, send_whatsapp
from src.storage.applied_store import AppliedJobsStore

logger = logging.getLogger("outreach")

AGENCY_EXCLUDE_KEYWORDS = (
    "manpower",
    "placement",
    "head hunter",
    "headhunter",
    "staffing",
    "consultan",
    "recruit",
    "hr solution",
    "talent acquisition",
    "outsourc",
    "jobwala",
    "naukri",
    "internshala",
)

GENERIC_COMPANY_NAMES = {"startup", "unknown", "company", "anonymous", "confidential", "n/a", "na"}


def is_valid_outreach_company(company: str) -> bool:
    """Returns False for generic names, excluded companies, and staffing/manpower agencies."""
    comp = (company or "").strip()
    if not comp or comp.lower() in GENERIC_COMPANY_NAMES:
        return False
    if is_excluded_company(comp):
        return False
    comp_low = comp.lower()
    if any(kw in comp_low for kw in AGENCY_EXCLUDE_KEYWORDS):
        return False
    return True


def generate_outreach_targets(limit: int = 15) -> List[Dict[str, Any]]:
    """Fetches high-priority applied companies from data/applied_jobs.json and builds outreach notes."""
    store = AppliedJobsStore()
    applied_jobs = store.get_all()

    today_str = datetime.date.today().isoformat()
    week_ago_str = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    tier_priority = {1: 0, 3: 1, 2: 2}

    # First stabilize newest date order (store.get_all() already reverses insertion order),
    # then prioritize today's & last-7-days applications and Tier 1 (GenAI) / Tier 3 (Agentic) startups.
    def _sort_key(job: Dict[str, Any]) -> Tuple[int, int, int, str]:
        applied_date = str(job.get("applied_at") or "")[:10]
        tier = job.get("target_tier") or 2
        is_today_bucket = 0 if applied_date == today_str else 1
        is_recent_bucket = 0 if applied_date >= week_ago_str else 1
        t_rank = tier_priority.get(tier, 3)
        # Negate ISO date lex order by reversing via char complement isn't needed if pre-sorted by date desc;
        # we only return fixed buckets here after pre-sorting by applied_date desc.
        return (is_today_bucket, is_recent_bucket, t_rank, "")

    applied_jobs.sort(key=lambda j: str(j.get("applied_at") or "")[:10], reverse=True)
    applied_jobs.sort(key=_sort_key)

    seen_companies = set()
    targets: List[Dict[str, Any]] = []

    for r in applied_jobs:
        comp = (r.get("company") or "").strip()
        if not is_valid_outreach_company(comp) or comp.lower() in seen_companies:
            continue
        outcome_low = (r.get("outcome") or "").strip().lower()
        if outcome_low in ("not selected", "rejected", "withdrawn", "expired"):
            continue
        tier = r.get("target_tier") or 2
        if tier not in (1, 2, 3):
            continue
        seen_companies.add(comp.lower())

        role = (r.get("title") or "AI Engineer").strip()
        cat = r.get("target_category") or "AI Engineering"

        google_query = f'site:linkedin.com/in/ "{comp}" ("technical recruiter" OR "talent acquisition" OR "engineering manager" OR "founder" OR "head of ai")'
        google_search_url = f"https://www.google.com/search?q={urllib.parse.quote(google_query)}"
        linkedin_search_url = f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote(comp + ' recruiter')}"

        if tier == 1:
            note = (
                f"Hi! Applied for {role} at {comp}. Built Rorak AI (FastAPI + Cloud Run RAG, "
                f"{PORTFOLIO_URL}) & multi-agent workflows for NVIDIA's AI hackathon. Would love to connect!"
            )
        elif tier == 3:
            note = (
                f"Hi! Applied for {role} at {comp}. Built a 5-agent stateful workflow for NVIDIA's "
                f"Agentic AI Hackathon & Rorak AI ({PORTFOLIO_URL}). Would love to connect!"
            )
        else:
            note = (
                f"Hi! Applied for {role} at {comp}. I build production Python/FastAPI backends "
                f"& LLM/RAG systems (Rorak AI, {PORTFOLIO_URL}; ISRO BAH finalist). Would love to connect!"
            )

        if len(note) > 300:
            note = note[:297] + "..."

        dm = (
            f"Hi [Name], thanks for connecting!\n\n"
            f"I recently submitted my application for the {role} position at {comp}. "
            f"Given {comp}'s focus in {cat.split('/')[0].strip()}, I wanted to briefly highlight my hands-on background:\n\n"
            f"• Rorak AI (Production RAG): Containerized FastAPI backend on Google Cloud Run with FAISS vector search and Groq Llama 3.3 (live at {PORTFOLIO_URL})\n"
            f"• Multi-Agent Systems: Designed a 5-agent collaborative scoping architecture for NVIDIA's Agentic AI Hackathon\n"
            f"• Backend Engineering: Clean Python/FastAPI APIs with pytest, Docker, and CI/CD pipelines\n\n"
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
            "followup_dm": dm,
        })
        if len(targets) >= limit:
            break

    return targets


def run_linkedin_outreach(limit: int = 15, phone: Optional[str] = None, send_wa: bool = True) -> List[Dict[str, Any]]:
    """Generates outreach targets from applied_jobs.json and optionally dispatches top 5 to WhatsApp."""
    print("=" * 65)
    print("      LINKEDIN RECRUITER & FOUNDER OUTREACH GENERATOR")
    print(f"      Candidate: {CANDIDATE_NAME} (+{DEFAULT_PHONE})")
    print("      Source:    data/applied_jobs.json")
    print("=" * 65)

    targets = generate_outreach_targets(limit=limit)
    print(f"Generated outreach messages for {len(targets)} applied companies.\n")

    for idx, t in enumerate(targets, 1):
        print(f"{idx:>2}. {t['company']} — {t['role']} [Tier {t['tier']}]")
        print(f"    Search: {t['linkedin_search']}")
        print(f"    Note ({t['note_len']}/300): {t['connection_note']}\n")

    if send_wa and targets:
        cfg = load_config()
        target_phone = normalize_phone(phone or cfg.get("preferred_target") or DEFAULT_PHONE)
        wa_lines = [
            "🎯 *Top LinkedIn Recruiter Outreach Queue*",
            f"👤 Candidate: {CANDIDATE_NAME}\n",
        ]
        for idx, t in enumerate(targets[:5], 1):
            wa_lines.append(
                f"*{idx}. {t['company']}* ({t['role']})\n"
                f"🔍 {t['linkedin_search']}\n"
                f"✉️ \"{t['connection_note']}\"\n"
            )
        send_whatsapp("\n".join(wa_lines), phone=target_phone)

    return targets
