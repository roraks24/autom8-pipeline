import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Root directories
SRC_DIR = Path(__file__).resolve().parent
BASE_DIR = SRC_DIR.parent
CONFIG_DIR = BASE_DIR / "config"
COOKIES_DIR = BASE_DIR / "cookies"
LOGS_DIR = BASE_DIR / "application_logs"
RESUMES_DIR = BASE_DIR / "tailored_resumes"
SCRIPTS_DIR = BASE_DIR / "scripts"

# Database
DB_PATH = BASE_DIR / "jobs.db"

# Ensure runtime directories exist
LOGS_DIR.mkdir(exist_ok=True)
RESUMES_DIR.mkdir(exist_ok=True)
CONFIG_DIR.mkdir(exist_ok=True)
COOKIES_DIR.mkdir(exist_ok=True)

# Candidate Defaults
DEFAULT_PHONE = "917877169982"
CANDIDATE_NAME = "Rohit Saini"
CANDIDATE_EMAIL = "rsaini2407@gmail.com"
PORTFOLIO_URL = "https://rohit-saini-dev.vercel.app"
LINKEDIN_URL = "https://www.linkedin.com/in/rorak/"
GITHUB_URL = "https://github.com/roraks24"

# Application Platform Policy (Strictly Internshala & Wellfound - 20 applications each daily)
ACTIVE_PLATFORMS = ["internshala", "wellfound"]
DAILY_TARGET_PER_PLATFORM = 20
TOTAL_DAILY_TARGET = 40
ENFORCE_ACTIVE_PLATFORMS = True

# Candidate Compensation & Work Policy (Strictly ZERO Unpaid Work)
# Absolute enforcement: never discover, stage, or apply to unpaid, volunteer, zero-stipend, or pro-bono roles
ALLOW_UNPAID_WORK = False
EXCLUDE_UNPAID_WORK = True

# Human-like pacing settings between consecutive applications (in seconds)
# Simulates authentic candidate behavior to prevent WAF, bot flags & account suspension
HUMAN_DELAY_MIN = 15.0  # Minimum delay between job applications
HUMAN_DELAY_MAX = 30.0  # Maximum delay between job applications


def get_config_file(filename: str) -> Path:
    """Returns path from config/ if exists, else falls back to BASE_DIR."""
    cfg_path = CONFIG_DIR / filename
    if cfg_path.exists():
        return cfg_path
    fallback = BASE_DIR / filename
    return fallback


def get_cookie_path(platform: str) -> Path:
    """Returns cookie JSON path for a platform (checking cookies/ then BASE_DIR)."""
    filename = f"{platform.lower()}_cookies.json"
    cp = COOKIES_DIR / filename
    if cp.exists():
        return cp
    fallback = BASE_DIR / filename
    return fallback


# Common configuration file paths
ANSWER_BANK_PATH = get_config_file("answer_bank.json")
MASTER_RESUME_PATH = get_config_file("master_resume.txt")
RESUME_TEMPLATE_PATH = get_config_file("resume_template.html")


def load_answer_bank() -> Dict[str, Any]:
    """Loads candidate answer bank from JSON."""
    path = get_config_file("answer_bank.json")
    if not path.exists():
        return {
            "personal": {
                "full_name": CANDIDATE_NAME,
                "email": CANDIDATE_EMAIL,
                "phone": f"+{DEFAULT_PHONE}",
                "linkedin": LINKEDIN_URL,
                "github": GITHUB_URL,
                "portfolio": PORTFOLIO_URL
            },
            "standard_answers": {
                "why_hire_me": (
                    "You should hire me because I don't just learn technologies \u2014 I use them to build working applications.\n\n"
                    "For example, I've built Rorak AI, a document-based AI assistant using FastAPI, RAG, FAISS, PostgreSQL, and LLM APIs. "
                    "I've also worked on backend APIs, authentication, and database integration.\n\n"
                    "I'm still early in my career, but I take ownership of what I build, I'm comfortable solving problems independently, "
                    "and I'm willing to learn whatever the project requires.\n\n"
                    "I'm not claiming to know everything. I'm saying that if you give me a real problem, I'll put in the effort to understand it, "
                    "build a solution, and keep improving it based on feedback."
                ),
                "require_visa_outside_india": "Yes",
                "require_visa_in_india": "No",
                "authorized_in_india": "Yes"
            }
        }
    return json.loads(path.read_text(encoding="utf-8"))


def load_whatsapp_config() -> Dict[str, Any]:
    """Loads WhatsApp messaging configuration."""
    path = get_config_file("whatsapp_config.json")
    if not path.exists():
        return {
            "primary_phone": DEFAULT_PHONE,
            "preferred_target": DEFAULT_PHONE,
            "callmebot": {}
        }
    return json.loads(path.read_text(encoding="utf-8"))


def get_master_resume_path() -> Path:
    """Returns path to master resume text file."""
    return get_config_file("master_resume.txt")


def get_resume_template_path() -> Path:
    """Returns path to HTML resume template."""
    return get_config_file("resume_template.html")
