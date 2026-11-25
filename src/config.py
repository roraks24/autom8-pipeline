import json
import os
from pathlib import Path
from typing import Any, Dict, Set

# Root directories
SRC_DIR = Path(__file__).resolve().parent
BASE_DIR = SRC_DIR.parent
CONFIG_DIR = BASE_DIR / "config"
COOKIES_DIR = BASE_DIR / "cookies"
DATA_DIR = BASE_DIR / "data"
RESUMES_DIR = BASE_DIR / "tailored_resumes"


def _load_dotenv(env_path: Path) -> None:
    """Lightweight .env loader (avoids hard dependency on python-dotenv)."""
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


_load_dotenv(BASE_DIR / ".env")

# Single JSON Database & Discovery Skip-Cache (Zero SQLite, Zero Screenshots)
APPLIED_DB_PATH = DATA_DIR / "applied_jobs.json"
SKIPPED_CACHE_PATH = DATA_DIR / "skipped_cache.json"
SAVE_SCREENSHOTS = False

# Persistent browser profile directory for authenticated Playwright sessions
CHROME_PROFILE_DIR = Path.home() / ".chrome_job_profile"
WHATSAPP_PROFILE_DIR = Path.home() / ".whatsapp_web_profile"

# Ensure runtime directories exist
CONFIG_DIR.mkdir(exist_ok=True)
COOKIES_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)
RESUMES_DIR.mkdir(exist_ok=True)

# Candidate Defaults
DEFAULT_PHONE = "917877169982"
CANDIDATE_NAME = "Rohit Saini"
CANDIDATE_EMAIL = "rsaini2407@gmail.com"
PORTFOLIO_URL = "https://rohit-saini-dev.vercel.app"
LINKEDIN_URL = "https://www.linkedin.com/in/rorak/"
GITHUB_URL = "https://github.com/roraks24"

# Application Platform Policy (Internshala & Wellfound - 20 applications each daily)
ACTIVE_PLATFORMS = ["internshala", "wellfound"]
DAILY_TARGET_PER_PLATFORM = 20
TOTAL_DAILY_TARGET = 40
ENFORCE_ACTIVE_PLATFORMS = True

# Candidate Compensation & Work Policy (Strictly ZERO Unpaid Work)
ALLOW_UNPAID_WORK = False
EXCLUDE_UNPAID_WORK = True

# Human-like pacing settings between consecutive applications (in seconds)
HUMAN_DELAY_MIN = 15.0
HUMAN_DELAY_MAX = 30.0


def get_config_file(filename: str) -> Path:
    """Returns canonical path inside config/ directory."""
    return CONFIG_DIR / filename


def get_cookie_path(platform: str) -> Path:
    """Returns canonical cookie JSON path inside cookies/ directory."""
    return COOKIES_DIR / f"{platform.lower().strip()}_cookies.json"


# Common configuration file paths
ANSWER_BANK_PATH = get_config_file("answer_bank.json")
BOARDS_PATH = get_config_file("boards.json")
MASTER_RESUME_PATH = get_config_file("master_resume.txt")
RESUME_TEMPLATE_PATH = get_config_file("resume_template.html")
WHATSAPP_CONFIG_PATH = get_config_file("whatsapp_config.json")


def load_answer_bank() -> Dict[str, Any]:
    """Loads candidate answer bank from config/answer_bank.json."""
    if not ANSWER_BANK_PATH.exists():
        return {
            "personal": {
                "full_name": CANDIDATE_NAME,
                "email": CANDIDATE_EMAIL,
                "phone": f"+{DEFAULT_PHONE}",
                "linkedin": LINKEDIN_URL,
                "github": GITHUB_URL,
                "portfolio": PORTFOLIO_URL,
            },
            "standard_answers": {
                "why_hire_me": (
                    "You should hire me because I don't just learn technologies — I use them to build working applications.\n\n"
                    "For example, I've built Rorak AI, a document-based AI assistant using FastAPI, RAG, FAISS, PostgreSQL, and LLM APIs. "
                    "I've also worked on backend APIs, authentication, and database integration.\n\n"
                    "I'm still early in my career, but I take ownership of what I build, I'm comfortable solving problems independently, "
                    "and I'm willing to learn whatever the project requires."
                ),
                "require_visa_outside_india": "Yes",
                "require_visa_in_india": "No",
                "authorized_in_india": "Yes",
            },
        }
    return json.loads(ANSWER_BANK_PATH.read_text(encoding="utf-8"))


def load_whatsapp_config() -> Dict[str, Any]:
    """Loads WhatsApp messaging configuration from config/whatsapp_config.json."""
    if not WHATSAPP_CONFIG_PATH.exists():
        return {
            "primary_phone": DEFAULT_PHONE,
            "preferred_target": DEFAULT_PHONE,
            "callmebot_api_key": "",
        }
    return json.loads(WHATSAPP_CONFIG_PATH.read_text(encoding="utf-8"))


def load_boards_config() -> Dict[str, Any]:
    """Loads search boards/directories configuration from config/boards.json."""
    if not BOARDS_PATH.exists():
        return {"internshala": [], "wellfound": []}
    return json.loads(BOARDS_PATH.read_text(encoding="utf-8"))


def get_master_resume_path() -> Path:
    """Returns path to master resume text file."""
    return MASTER_RESUME_PATH


def get_resume_template_path() -> Path:
    """Returns path to HTML resume template."""
    return RESUME_TEMPLATE_PATH


def get_groq_api_key() -> str:
    """Returns configured Groq API key from environment or .env."""
    return os.environ.get("GROQ_API_KEY", "").strip()


def get_groq_model() -> str:
    """Returns configured Groq model identifier."""
    return os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b").strip()


def load_excluded_companies() -> Set[str]:
    """Loads manually excluded company names from config/excluded.txt."""
    path = get_config_file("excluded.txt")
    if not path.exists():
        return set()
    companies: Set[str] = set()
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            companies.add(line.lower())
    return companies
