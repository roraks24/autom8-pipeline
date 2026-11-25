import json
import logging
import re
from functools import lru_cache
from typing import List, Optional

import requests

from src.config import (
    GITHUB_URL,
    LINKEDIN_URL,
    PORTFOLIO_URL,
    get_groq_api_key,
    get_groq_model,
    load_answer_bank,
)

logger = logging.getLogger("llm")

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
FALLBACK_MODELS = ["openai/gpt-oss-120b", "qwen/qwen3.8-27b"]


@lru_cache(maxsize=1)
def _load_candidate_facts() -> str:
    """Builds a compact, token-efficient factual brief grounded strictly in verified candidate records."""
    ans = load_answer_bank()
    personal = ans.get("personal", {})
    edu = ans.get("education", {})
    prefs = ans.get("work_preferences", {})

    facts = {
        "name": personal.get("full_name", "Rohit Saini"),
        "location": f"{personal.get('city', 'Jaipur')}, {personal.get('state', 'Rajasthan')}, {personal.get('country', 'India')}",
        "portfolio": personal.get("portfolio", PORTFOLIO_URL),
        "github": personal.get("github", GITHUB_URL),
        "linkedin": personal.get("linkedin", LINKEDIN_URL),
        "education": f"{edu.get('degree', 'B.Tech')} in {edu.get('field_of_study', 'CSE (AI & ML)')}, {edu.get('institution', 'JECRC University, Jaipur')} ({edu.get('current_year', '2nd year')}, {edu.get('start_year', 2025)}-{edu.get('graduation_year', 2029)})",
        "availability": prefs.get("notice_period", "Immediately available (0 days)"),
        "relocation": prefs.get("relocation", "Yes, open to relocate across India"),
        "weekly_hours": prefs.get("weekly_hours", "40 hours/week full-time or 20-25 hours/week part-time"),
        "experience": [
            "Artificial Intelligence Engineer Intern at Srishti GenAI (Nov 2026 - Present, Remote Bengaluru): Contributing to initial AI project architecture using Python and FastAPI.",
            "Artificial Intelligence Intern at InAmigos Foundation (Aug 2026 - Sep 2026, Jaipur): Researched practical AI workflows and delivered automation tasks.",
        ],
        "verified_projects": [
            "Rorak AI V2 (Deployed Document-Grounded RAG): FastAPI, PostgreSQL, SQLAlchemy, Alembic, FAISS top-10 + cross-encoder reranking to top-3, Groq LLM, JWT/bcrypt, prompt-injection safeguards, Docker, AWS/Cloud Run CI.",
            "Agent Co (Autonomous Agentic Platform): FastAPI + LangGraph planner/executor, multi-provider adaptive model routing (cost/latency/capability scoring + fallback), schema-validated web/GitHub/file tools, SSE audit streams, PostgreSQL/Docker Compose.",
            "PharmaShield AI: FastAPI, LangGraph, Groq, SQLAlchemy, PostgreSQL, React/Redux complaint workflow for structured record extraction, duplicate detection, root-cause hypotheses, and CAPA review.",
            "FastAPI Blogging API: Modular CRUD REST routers, JWT auth, background file processing, pytest coverage.",
            "ISRO BAH 2026 Finalist (Team Astroseekers): End-to-end TESS light-curve exoplanet detection pipeline (TLS/BLS, Random Forest + rule classifier, MCMC) validated on WASP-43 b & TIC 249064185.",
            "FreelanceIQ (NVIDIA + gnani.ai Agentic AI Hackathon): 5-agent collaborative project scoping workflow.",
            "TrustLayer (IIT Roorkee Cognizance 2026): FastAPI + Groq milestone decomposition & escrow review prototype.",
        ],
        "verified_skills": [
            "Python", "SQL", "JavaScript", "HTML", "CSS", "React", "Redux Toolkit",
            "FastAPI", "Flask", "REST APIs", "SQLAlchemy", "Alembic", "PostgreSQL", "SQLite", "JWT", "bcrypt", "pytest",
            "RAG", "Embeddings", "FAISS", "MMR", "Cross-Encoder Reranking", "LangChain", "LangGraph", "Multi-Agent Systems",
            "Groq API", "OpenAI API", "SSE Streaming", "Adaptive Model Routing",
            "Docker", "Docker Compose", "AWS", "Cloud Run", "Firebase", "Git", "GitHub", "Linux", "scikit-learn", "Pandas", "NumPy",
        ],
    }
    return json.dumps(facts, indent=1)


SYSTEM_GUARDRAILS = """You write concise, authentic job application answers for Rohit Saini.
TRUTHFULNESS RULES:
- Use ONLY facts in the JSON profile below. Never invent jobs, years of experience, metrics, revenue, or unverified skills.
- Say "hands-on internship & production project experience" (NEVER exaggerate into multiple years of full-time corporate work).
- Verified portfolio URL is ONLY https://rohit-saini-dev.vercel.app (never rorak.tech).
- Sound direct and engineering-focused; avoid generic AI filler ("I am thrilled", "As an AI").

CANDIDATE FACTS:
{facts}"""


def chat_complete(
    user_prompt: str,
    system_prompt: Optional[str] = None,
    max_tokens: int = 200,
    temperature: float = 0.2,
) -> Optional[str]:
    """Calls Groq Chat Completions API cleanly with fallback models and graceful offline fallback."""
    api_key = get_groq_api_key()
    if not api_key:
        return None

    sys_msg = system_prompt or SYSTEM_GUARDRAILS.format(facts=_load_candidate_facts())
    primary_model = get_groq_model()
    models_to_try = [primary_model] + [m for m in FALLBACK_MODELS if m != primary_model]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    for model_name in models_to_try:
        effective_max_tokens = min(max(max_tokens * 3, 550), 950)
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": effective_max_tokens,
            "temperature": temperature,
        }
        if "gpt-oss" in model_name:
            payload["reasoning_effort"] = "low"
        elif "qwen" in model_name:
            payload["reasoning_effort"] = "none"

        try:
            resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=14)
            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices") or []
                if choices:
                    choice = choices[0]
                    content = (choice.get("message", {}).get("content") or "").strip()
                    content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
                    if content and (choice.get("finish_reason") != "length" or len(content.split()) >= 8):
                        return content
                    logger.warning(f"Groq API [{model_name}] output truncated/empty; trying fallback.")
            else:
                logger.warning(f"Groq API [{model_name}] HTTP {resp.status_code}: {resp.text[:140]}")
        except Exception as e:
            logger.warning(f"Groq API [{model_name}] error: {e}")

    return None


def align_expected_salary(
    posted_salary: str = "",
    is_numeric: bool = False,
    currency_hint: str = "",
) -> str:
    """
    Aligns expected salary/stipend with the employer's posted range
    to avoid automatic disqualification for over-budget expectations.
    """
    raw = (posted_salary or "").strip()
    low = raw.lower()
    is_usd = "$" in raw or "usd" in low or "$" in currency_hint or "usd" in currency_hint.lower()

    nums = [int(n.replace(",", "")) for n in re.findall(r"\b\d[\d,]*\b", raw)]
    nums = [n for n in nums if n >= 100 or "k" in low or "lpa" in low]

    if nums:
        if "$" in raw and "k" in low and max(nums) < 1000:
            nums = [n * 1000 for n in nums]
        elif "lpa" in low and max(nums) < 100:
            nums = [n * 100000 for n in nums]

        target_num = nums[-1] if len(nums) == 1 else round((nums[0] + nums[-1]) / 2)
        if is_numeric:
            return str(target_num)
        if is_usd:
            unit = "/year" if ("year" in low or "annu" in low or target_num >= 10000) else "/month"
            return f"${target_num:,} {unit} (aligned with listing range)"
        unit = "/year" if ("year" in low or "annu" in low or "lpa" in low or target_num >= 100000) else "/month"
        return f"₹{target_num:,} {unit} (aligned with listing range, open to discussion)"

    if is_numeric:
        return "1500" if is_usd else "15000"
    return "$1,500 - $2,000 /month" if is_usd else "₹15,000 - ₹25,000 /month (flexible per role scope)"


def generate_tailored_pitch(
    company: str,
    job_title: str,
    jd_text: str = "",
    skills_required: Optional[List[str]] = None,
    max_words: int = 105,
) -> Optional[str]:
    """Generates a 3-sentence pitch note grounded in company JD + verified builds."""
    skills_str = ", ".join(skills_required[:10]) if skills_required else "Not specified"
    jd_excerpt = (jd_text or "").strip()[:1800] or "No detailed JD provided; infer carefully from title."

    prompt = f"""Write a concise, genuine 3-sentence application note (<= {max_words} words) for:
Company: {company} | Role: {job_title}
Listed Skills: {skills_str}
Job Description: {jd_excerpt}

Structure:
1. Reference what {company} is building or needs in {job_title} from the JD.
2. Highlight 1-2 directly matching verified projects/experience (Srishti GenAI, Rorak AI V2, Agent Co, PharmaShield AI, ISRO BAH 2026, FreelanceIQ, or FastAPI REST API) with concrete stack details.
3. Confirm immediate availability and share portfolio (https://rohit-saini-dev.vercel.app) + GitHub (https://github.com/roraks24).
Plain text paragraph only."""

    return chat_complete(prompt, max_tokens=180, temperature=0.2)


def answer_screening_question(
    question_label: str,
    field_type: str = "textarea",
    options: Optional[List[str]] = None,
    company: str = "",
    job_title: str = "",
    jd_text: str = "",
    posted_salary: str = "",
    skills_required: Optional[List[str]] = None,
) -> Optional[str]:
    """Synthesizes answers for custom employer screening questions using Groq + Master Resume."""
    if not question_label or not question_label.strip():
        return None

    jd_excerpt = (jd_text or "").strip()[:1200]
    skills_str = ", ".join(skills_required[:8]) if skills_required else ""
    aligned_sal = align_expected_salary(posted_salary, is_numeric=(field_type == "number"), currency_hint=question_label)

    if options:
        opts_str = " | ".join(str(o) for o in options[:20])
        prompt = f"""Pick the BEST option verbatim for this dropdown:
Company: {company} | Role: {job_title}
Question: "{question_label}"
Options (reply ONLY with the exact option string): {opts_str}"""
        reply = chat_complete(prompt, max_tokens=40, temperature=0.0)
        if reply:
            clean = reply.strip().strip('"').strip("'")
            for opt in options:
                if clean.lower() == str(opt).strip().lower():
                    return str(opt)
            for opt in options:
                if str(opt).strip().lower() in clean.lower():
                    return str(opt)
        return None

    constraint = "a single integer number only" if field_type == "number" else (
        "one crisp sentence (<= 25 words)" if field_type == "text" else "a direct 2-4 sentence engineering answer (<= 95 words)"
    )

    prompt = f"""Answer this employer screening question truthfully based ONLY on CANDIDATE FACTS.
Company: {company} | Role: {job_title} | Skills: {skills_str}
Posted Compensation: {posted_salary or 'Not stated'} (aligned expectation: {aligned_sal})
JD Excerpt: {jd_excerpt}
Question: "{question_label}"

Reply with {constraint}. Output ONLY the exact field value with no intro/quotes."""

    return chat_complete(prompt, max_tokens=170 if field_type == "textarea" else 60, temperature=0.2)


def generate_resume_summary(
    company: str,
    job_title: str,
    jd_text: str = "",
    matched_skills: Optional[List[str]] = None,
) -> Optional[str]:
    """Synthesizes a targeted 2-3 sentence ATS Professional Summary grounded in verified facts."""
    skills_str = ", ".join(matched_skills[:8]) if matched_skills else "Python, FastAPI, GenAI, RAG, LangGraph"
    jd_excerpt = (jd_text or "").strip()[:1200]

    prompt = f"""Write a tight 2-3 sentence ATS Resume Professional Summary (<= 55 words) for Rohit Saini applying to:
Role: {job_title} at {company}
Matched Verified Skills: {skills_str}
JD Excerpt: {jd_excerpt}

Include "AI Engineer Intern at Srishti GenAI" and "B.Tech CSE (AI/ML)". Output plain text only."""

    return chat_complete(prompt, max_tokens=110, temperature=0.2)
