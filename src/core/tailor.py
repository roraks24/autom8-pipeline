import html
import json
import logging
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import jinja2
from playwright.sync_api import sync_playwright

from src.config import (
    CANDIDATE_EMAIL,
    CANDIDATE_NAME,
    DB_PATH,
    DEFAULT_PHONE,
    GITHUB_URL,
    LINKEDIN_URL,
    PORTFOLIO_URL,
    RESUMES_DIR,
    get_resume_template_path,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("tailor")

VERIFIED_SKILLS_REPOSITORY = {
    "Backend & APIs": [
        "Python", "FastAPI", "Flask", "REST APIs", "SQLAlchemy", "Alembic", "PostgreSQL",
        "SQLite", "JWT Authentication", "bcrypt", "file processing", "pytest", "AsyncIO", "API Integration"
    ],
    "GenAI & Multi-Agent": [
        "Prompt Engineering", "Groq API (Llama 3.3 70B)", "OpenAI API", "RAG", "Embeddings",
        "FAISS Vector Search", "MMR Retrieval", "Cross-Encoder Reranking", "LangChain", "LangGraph",
        "Multi-Step Agent Workflows", "Adaptive Model Routing", "Autonomous Agents", "Tool Calling"
    ],
    "AI Systems & Integration": [
        "Tool Registries", "Web Search Tools", "GitHub API Integration", "Source Verification",
        "SSE Streaming", "Adaptive Model Routing", "Prompt-Injection Mitigation", "Workflow Audit Trails"
    ],
    "Cloud, DevOps & Tools": [
        "Docker", "Docker Compose", "Google Cloud Run", "Firebase Hosting", "CI Workflows",
        "Health Checks", "Rate Limiting", "Secret-Redacted Logging", "Git & GitHub", "Linux / Bash", "PowerShell"
    ],
    "Data & Machine Learning": [
        "scikit-learn", "Pandas", "NumPy", "Machine Learning", "Data Processing",
        "lightkurve", "Transit Least Squares (TLS)", "Astropy", "batman", "emcee"
    ],
    "Languages & Web": [
        "Python", "SQL", "JavaScript", "HTML", "CSS", "React", "Redux Toolkit"
    ]
}

PROJECTS_BANK = [
    {
        "id": "agent_co",
        "name": "Agent Co - Autonomous Agentic Execution Platform",
        "tag": "Independent Engineering Project",
        "date": "2026",
        "stack": "FastAPI, LangGraph, Groq, OpenAI, Anthropic, Docker Compose, PostgreSQL, SSE",
        "link": GITHUB_URL,
        "link_text": "github.com/roraks24",
        "keywords": [
            "agents", "multi-agent", "agentic", "langgraph", "fastapi", "sse", "streaming",
            "routing", "tool calling", "autonomous", "python", "model routing", "orchestration", "docker compose"
        ],
        "bullets": [
            "Engineered an autonomous agentic execution engine with FastAPI and LangGraph that decomposes complex objectives into structured plans and executes tools iteratively across research and data workflows.",
            "Implemented adaptive multi-provider model routing with task classification, requirement extraction, capability/cost/latency scoring, and fallback across Groq, OpenAI, Anthropic, and local profiles.",
            "Integrated schema-validated web/GitHub/data tools, deliverable verification, real-time SSE audit streams, and PostgreSQL persistence with SQLAlchemy, Alembic, and Docker Compose."
        ]
    },
    {
        "id": "rorak_ai",
        "name": "Rorak AI V2 - Document-Grounded AI Assistant",
        "tag": "Deployed Live Project",
        "date": "2026",
        "stack": "FastAPI, PostgreSQL, SQLAlchemy, Alembic, FAISS, Hugging Face, Groq LLM, Cloud Run",
        "link": PORTFOLIO_URL,
        "link_text": "rohit-saini-dev.vercel.app",
        "keywords": [
            "rag", "fastapi", "faiss", "groq", "llm", "docker", "gcp", "cloud run",
            "vector search", "embeddings", "reranking", "genai", "api", "python", "postgresql"
        ],
        "bullets": [
            "Architected and deployed a multi-format document RAG assistant supporting PDF, DOCX, TXT, Markdown, and CSV ingestion with FastAPI, FAISS, and Groq LLM generation.",
            "Implemented top-10 retrieval with cross-encoder reranking to top 3, persistent conversation memory, JWT/bcrypt authentication, per-user resource isolation, and prompt-injection mitigations.",
            "Containerized with Docker and deployed on Google Cloud Run with warm-instance scaling, health checks, rate limiting, and automated CI workflows."
        ]
    },
    {
        "id": "pharmashield_ai",
        "name": "PharmaShield AI - Pharmaceutical Complaint Intelligence Platform",
        "tag": "Full-Stack AI Project",
        "date": "2026",
        "stack": "React, Redux Toolkit, FastAPI, LangGraph, Groq, SQLAlchemy, PostgreSQL",
        "link": GITHUB_URL,
        "link_text": "github.com/roraks24",
        "keywords": [
            "react", "full stack", "full-stack", "fastapi", "langgraph", "groq", "postgresql",
            "intelligence", "complaint", "nlp", "llm", "genai", "frontend"
        ],
        "bullets": [
            "Built an enterprise complaint intelligence platform using React, Redux Toolkit, FastAPI, LangGraph, and PostgreSQL to transform unstructured PDF and text complaints into structured records.",
            "Designed human-in-the-loop AI assistance for risk assessment, completeness validation, duplicate detection, root-cause hypothesis generation, and CAPA recommendations.",
            "Integrated structured record generation with natural-language workflow updates and auditable review trails."
        ]
    },
    {
        "id": "fastapi_api",
        "name": "FastAPI Production REST & Auth Service",
        "tag": "Backend Service",
        "date": "2026",
        "stack": "FastAPI, SQLAlchemy, Alembic, PostgreSQL/SQLite, JWT, bcrypt, pytest, Docker",
        "link": GITHUB_URL,
        "link_text": "github.com/roraks24",
        "keywords": [
            "fastapi", "flask", "django", "sql", "sqlalchemy", "jwt", "auth", "rest",
            "api", "apis", "testing", "pytest", "backend", "python", "crud", "database", "alembic"
        ],
        "bullets": [
            "Engineered modular REST API services featuring CRUD endpoints, SQLAlchemy ORM data models, Alembic migrations, and secure JWT/bcrypt authentication.",
            "Structured router-based design, custom middleware/dependencies, file uploads, and background tasks for scalable data throughput.",
            "Authored automated unit and integration test suites using pytest prior to production deployment."
        ]
    },
    {
        "id": "freelance_iq",
        "name": "FreelanceIQ - Multi-Agent Freelance Scoping System",
        "tag": "Hackathon Submission",
        "date": "2026",
        "stack": "Python, Multi-Agent Architecture, LangGraph, LLM Prompt Chains, Task Delegation",
        "link": GITHUB_URL,
        "link_text": "Team AgentSutra",
        "keywords": [
            "agents", "multi-agent", "agentic", "tool calling", "prompt engineering",
            "orchestration", "langgraph", "langchain", "autonomous", "python", "automation"
        ],
        "bullets": [
            "Designed a multi-agent system with 5 specialized agents to automate client requirement elicitation and freelance project scoping for NVIDIA + gnani.ai Agentic AI Hackathon.",
            "Implemented structured agent-to-agent communication protocols and fallback consensus logic for requirement analysis.",
            "Constructed end-to-end evaluation flow reducing scoping time from hours to minutes with high repeatability."
        ]
    },
    {
        "id": "isro_bah",
        "name": "ISRO BAH 2026 - AI Exoplanet Detection Pipeline",
        "tag": "Hackathon Finalist",
        "date": "2026",
        "stack": "Python, scikit-learn, Transit Least Squares (TLS), lightkurve, astropy, batman",
        "link": "",
        "link_text": "",
        "keywords": [
            "scikit-learn", "data", "data science", "ml", "machine learning", "scientific",
            "python", "pipeline", "astropy", "algorithms", "modeling"
        ],
        "bullets": [
            "Engineered an automated signal processing and machine learning pipeline to detect planetary transits from noisy telescope light-curve feeds.",
            "Validated transit-fitting algorithms against confirmed exoplanets (WASP-43 b, TIC 249064185), advancing to ISRO BAH 2026 National Finale.",
            "Authored formal mathematical methodology documentation and a 10-item validation test report."
        ]
    },
    {
        "id": "trustlayer",
        "name": "TrustLayer - AI-Powered Escrow Platform",
        "tag": "Deployed Prototype",
        "date": "2026",
        "stack": "FastAPI, Groq API, Milestone Decomposition, AI Review, Escrow Contracts",
        "link": GITHUB_URL,
        "link_text": "IIT Roorkee Cognizance",
        "keywords": [
            "escrow", "freelance", "groq", "milestone", "decomposition", "ai review", "contracts", "python"
        ],
        "bullets": [
            "Co-developed an AI-powered freelance escrow prototype with employer/freelancer journeys, milestone checklists, and dynamic project decomposition for IIT Roorkee Cognizance 2026.",
            "Integrated Groq-powered milestone generation, AI-assisted deliverable review, confidence-based payment decisions, and a freelancer reliability score (PFI)."
        ]
    }
]


def analyze_job_requirements(target_title: str, target_company: str, jd_text: str = "", skills_required: Optional[List[str]] = None) -> Dict[str, Any]:
    """Deeply analyzes target job title, company, and JD text to derive ATS focus."""
    combined = f"{target_title} {target_company} {jd_text}".lower()
    if skills_required:
        combined += " " + " ".join(skills_required).lower()

    cat_scores = {
        "GenAI & Multi-Agent": 0,
        "Backend & APIs": 0,
        "AI Systems & Integration": 0,
        "Cloud, DevOps & Tools": 0,
        "Data & Machine Learning": 0,
        "Languages & Web": 0
    }

    category_keywords = {
        "GenAI & Multi-Agent": ["agent", "multi-agent", "agentic", "langchain", "langgraph", "rag", "vector", "llm", "genai", "prompt", "openai", "groq", "retrieval", "sse", "routing"],
        "Backend & APIs": ["backend", "fastapi", "flask", "django", "rest", "api", "apis", "sql", "sqlalchemy", "jwt", "database", "crud", "pytest", "developer", "software engineer", "alembic", "postgres"],
        "AI Systems & Integration": ["system", "tool", "integration", "github", "stream", "sse", "workflow", "audit", "security", "injection"],
        "Cloud, DevOps & Tools": ["docker", "cloud", "aws", "gcp", "linux", "git", "ci/cd", "deployment", "kubernetes", "firebase", "run"],
        "Data & Machine Learning": ["machine learning", "ml", "data science", "scikit-learn", "pandas", "numpy", "data analysis", "analytics", "modeling", "algorithms", "astropy"],
        "Languages & Web": ["react", "javascript", "frontend", "full stack", "fullstack", "web", "html", "css", "redux"]
    }

    for cat, kws in category_keywords.items():
        for kw in kws:
            if kw in combined:
                cat_scores[cat] += 2 if kw in target_title.lower() else 1

    project_scores = []
    for proj in PROJECTS_BANK:
        score = sum(2 if kw in target_title.lower() else 1 for kw in proj["keywords"] if kw in combined)
        project_scores.append((score, proj))
    project_scores.sort(key=lambda x: -x[0])

    top_projects = [p for _, p in project_scores[:3]]

    sorted_cats = sorted(cat_scores.keys(), key=lambda c: -cat_scores[c])
    tailored_categories = []
    matched_all_skills = []

    for cat in sorted_cats:
        cat_skills = VERIFIED_SKILLS_REPOSITORY.get(cat, [])
        if not cat_skills:
            continue
        matched = [s for s in cat_skills if s.lower() in combined]
        unmatched = [s for s in cat_skills if s.lower() not in combined]
        matched_all_skills.extend(matched)
        ordered_skills = matched + unmatched
        tailored_categories.append({
            "name": cat,
            "skills": ", ".join(ordered_skills),
            "matched_count": len(matched)
        })

    top_cat = sorted_cats[0]
    if "Agent" in target_title or "agent" in combined or top_cat == "GenAI & Multi-Agent":
        focus = "autonomous agentic execution platforms (Agent Co with LangGraph), multi-agent scoping systems, and production RAG pipelines"
    elif "Data" in target_title or top_cat == "Data & Machine Learning":
        focus = "machine learning pipelines (ISRO BAH 2026 finalist), data processing, and predictive modeling"
    elif top_cat == "Backend & APIs":
        focus = "production Python backends (FastAPI/SQLAlchemy/Alembic/PostgreSQL), RESTful API engineering, and containerized Cloud Run deployments"
    elif "React" in target_title or "Full Stack" in target_title or top_cat == "Languages & Web":
        focus = "full-stack AI application development (React/FastAPI/LangGraph), structured workflow intelligence, and responsive web systems"
    else:
        focus = "end-to-end GenAI application development, adaptive LLM model routing, and scalable Python architectures"

    summary = (
        f"AI Engineer Intern at Srishti GenAI and B.Tech CSE (AI/ML) developer specializing in {focus}. "
        f"Hands-on builder with deployed production systems (Rorak AI V2, Agent Co autonomous platform) and competitive hackathon finalist honors (ISRO BAH 2026, NVIDIA Agentic AI). "
        f"Skilled in Python, FastAPI, PostgreSQL, SQLAlchemy, modern LLM/RAG architectures, Docker, and rapid engineering delivery for {target_company}."
    )

    return {
        "top_category": top_cat,
        "selected_projects": top_projects,
        "skill_categories": tailored_categories[:4],
        "matched_skills": matched_all_skills,
        "summary": summary
    }


def tailor_resume_data(target_title: str, target_company: str, jd_text: str = "", skills_required: Optional[List[str]] = None) -> Dict[str, Any]:
    """Generates the complete context for rendering an ATS-optimized resume."""
    analysis = analyze_job_requirements(target_title, target_company, jd_text, skills_required)

    return {
        "name": CANDIDATE_NAME.upper(),
        "target_title": target_title or "AI Engineering | GenAI & Python Backend",
        "location": "Jaipur, Rajasthan, India",
        "email": CANDIDATE_EMAIL,
        "phone": f"+{DEFAULT_PHONE}",
        "github": GITHUB_URL,
        "linkedin": LINKEDIN_URL,
        "portfolio": PORTFOLIO_URL,
        "summary": analysis["summary"],
        "skill_categories": analysis["skill_categories"],
        "skills_genai": ", ".join(VERIFIED_SKILLS_REPOSITORY["GenAI & Multi-Agent"]),
        "skills_backend": ", ".join(VERIFIED_SKILLS_REPOSITORY["Backend & APIs"]),
        "skills_cloud": ", ".join(VERIFIED_SKILLS_REPOSITORY["Cloud, DevOps & Tools"]),
        "skills_data": ", ".join(VERIFIED_SKILLS_REPOSITORY["Data & Machine Learning"]),
        "projects": analysis["selected_projects"],
        "matched_skills": analysis["matched_skills"],
        "top_category": analysis["top_category"]
    }


def render_html_template(template_str: str, context: Dict[str, Any]) -> str:
    """Renders HTML template using Jinja2."""
    template = jinja2.Template(template_str)
    return template.render(**context)


def generate_pdf(context: Dict[str, Any], output_path: Path) -> Path:
    """Renders HTML template and compiles directly to an ATS-compliant PDF via Playwright Chromium."""
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    template_path = get_resume_template_path()
    template_str = template_path.read_text(encoding="utf-8")
    rendered_html = render_html_template(template_str, context)

    temp_html_path = output_path.with_suffix(".html")
    temp_html_path.write_text(rendered_html, encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(temp_html_path.as_uri())
        page.pdf(
            path=str(output_path),
            format="A4",
            print_background=True,
            margin={"top": "10mm", "bottom": "10mm", "left": "10mm", "right": "10mm"}
        )
        browser.close()

    if temp_html_path.exists():
        temp_html_path.unlink()

    logger.info(f"✅ Generated ATS PDF resume ({output_path.stat().st_size} bytes): {output_path.name}")
    return output_path


def get_or_create_resume(company: str, title: str, notes: str = "") -> Path:
    """Dynamically generates a freshly tailored ATS-compliant PDF resume for the target job."""
    clean_comp = re.sub(r"[^a-zA-Z0-9_-]", "_", company)
    clean_title = re.sub(r"[^a-zA-Z0-9_-]", "_", title)[:30]
    expected_pdf = RESUMES_DIR / f"Rohit_Saini_{clean_comp}_{clean_title}.pdf"

    print(f"  [JD Review] Analyzing job requirements for {company} - {title}...")
    ctx = tailor_resume_data(target_title=title, target_company=company, jd_text=notes)
    generate_pdf(ctx, expected_pdf)
    matched = ctx.get("matched_skills", [])
    print(f"  [ATS Tailor] Matched Skills: {', '.join(matched[:5]) if matched else 'Core Python / GenAI'}")
    print(f"  [ATS Tailor] Compiled ATS resume: {expected_pdf.name}")
    return expected_pdf


class ATSResumeTailor:
    """Object-oriented wrapper for resume tailoring."""
    @staticmethod
    def tailor_and_generate(company: str, title: str, jd_text: str = "") -> Path:
        return get_or_create_resume(company, title, jd_text)
