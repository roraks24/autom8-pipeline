import re
from typing import Optional, Tuple

from src.config import load_excluded_companies

TIER_1_PATTERNS = [
    r"\bgen\s*ai\b",
    r"\bgenai\b",
    r"\bgenerative\s*ai\b",
    r"\bllm\b",
    r"\blarge\s*language\s*model",
    r"\brag\b",
    r"\brag\s*engineer\b",
    r"\brag\s*developer\b",
    r"\bprompt\s*engineer",
    r"\bprompt\s*engineering\b",
]

TIER_3_PATTERNS = [
    r"\bagentic\b",
    r"\bai\s*agents?\b",
    r"\bagents?\s*dev",
    r"\bai\s*automation\b",
    r"\bai\s*workflow\b",
    r"\blanggraph\b",
    r"\bvoice\s*ai\b",
    r"\bai\s*systems?\b",
    r"\bautogen\b",
    r"\bcrewai\b",
]

TIER_2_PATTERNS = [
    r"\bapplied\s*ai\b",
    r"\bai\s*engineer",
    r"\bai\s*engineering\b",
    r"\bai\s*software\b",
    r"\bapplied\s*genai\b",
    r"\bai\s*developer\b",
    r"\bartificial\s*intelligence\b",
    r"\bnatural\s*language\s*processing\b",
    r"\bnlp\s*engineer\b",
    r"\bai\s*(&|and|\+)?\s*full[- ]?stack\b",
    r"\bai\s*full[- ]?stack\b",
    r"\bai\s*product\b",
    r"\bai\s*web\b",
    r"\bai\s*intern\b",
    r"\bai\s*trainee\b",
    r"\bai\s*solutions?\b",
    r"\bpython\s*developer\b",
    r"\bpython\s*development\b",
    r"\bpython\s*django\b",
    r"\bpython\s*fastapi\b",
    r"\bpython\s*programming\b",
    r"\bbackend\s*developer\b",
    r"\bbackend\s*development\b",
    r"\bbackend\s*engineer\b",
    r"\bfull[- ]?stack\s*developer\b",
    r"\bfull[- ]?stack\s*development\b",
    r"\bfull[- ]?stack\s*engineer\b",
    r"\bsoftware\s*developer\b",
    r"\bsoftware\s*development\b",
    r"\bsoftware\s*engineer\b",
    r"\bsoftware\s*engineering\b",
    r"\bmachine\s*learning\b",
    r"\bdeep\s*learning\b",
    r"\bdata\s*science\b",
    r"\bdata\s*scientist\b",
    r"\bdata\s*engineer\b",
    r"\bdata\s*engineering\b",
    r"\bweb\s*development\b",
    r"\bweb\s*developer\b",
    r"\bfrontend\s*development\b",
    r"\bfrontend\s*developer\b",
    r"\bfront[- ]?end\b",
    r"\bnode\.?js\b",
    r"\breact(\.js|js)?\b",
    r"\bdjango\b",
    r"\bfastapi\b",
    r"\bcomputer\s*science\b",
    r"\bml\s*engineer\b",
    r"\bml\s*developer\b",
    r"\bai\s*/\s*ml\b",
]

INTERNSHIP_PATTERNS = [
    r"\bintern\b",
    r"\binterns\b",
    r"\binternship\b",
    r"\binternships\b",
    r"\btrainee\b",
    r"\bapprentice\b",
    r"\bapprenticeship\b",
    r"\bfellow\b",
    r"\bfellowship\b",
]

EXCLUDE_PATTERNS = [
    r"\bfemale\b",
    r"\bvideo\b",
    r"\beditor\b",
    r"\bgrowth\b",
    r"\boperations\b",
    r"\btrainer\b",
    r"\bteacher\b",
    r"\bcourse\s*developer\b",
    r"\bartist\b",
    r"\bmagician\b",
    r"\bmarketing\b",
    r"\bsales\b",
    r"\bbusiness\s*analyst\b",
    r"\bdata\s*collector\b",
    r"\bhr\b",
    r"\brecruiter\b",
    r"\bcontent\b",
    r"\bcopywriter\b",
    r"\blegal\b",
    r"\bspanish\b",
    r"\btelecaller\b",
    r"\bcounselor\b",
    r"\baccountant\b",
]

# Stacks missing from candidate's verified project portfolio (keeps 40/day quota high-fit)
UNMATCHED_STACK_PATTERNS = [
    r"\bflutter\b",
    r"\bdart\b",
    r"\breact\s*native\b",
    r"\bwordpress\b",
    r"\bshopify\b",
    r"\bwix\b",
    r"\bphp\b",
    r"\blaravel\b",
    r"\b\.net\b",
    r"\bandroid\b",
    r"\bios\b",
    r"\bsalesforce\b",
    r"\bsap\b",
    r"\bmanual\s*testing\b",
    r"\bwindows\s*security\b",
]

SENIOR_PATTERNS = [
    r"\bsenior\b",
    r"\bsr\.?\b",
    r"\bstaff\b",
    r"\bprincipal\b",
    r"\blead\b",
    r"\bmanager\b",
    r"\bdirector\b",
    r"\bhead\b",
    r"\bvp\b",
    r"\barchitect\b",
]

EXPERIENCE_MISMATCH_PATTERNS = [
    r"\b(?:[2-9]\s*[-–to]+\s*(?:\d+|[4-9])|[2-9]\s*\+)\s*(?:years?|yrs?|yoe)\b",
    r"\b(?:min(?:imum)?|at\s*least)\s*[2-9]\+?\s*(?:years?|yrs?)\b",
    r"\bmid[- ]?level\b",
    r"\bsde[- ]?(?:2|3|ii|iii)\b",
]

UNPAID_PATTERNS = [
    r"\bunpaid\b",
    r"\bno\s*stipend\b",
    r"\b0\s*stipend\b",
    r"\bwithout\s*stipend\b",
    r"\bzero\s*stipend\b",
    r"\bvolunteer\b",
    r"\bvolunteering\b",
    r"\bpro\s*bono\b",
    r"\bpro-bono\b",
    r"\bno\s*salary\b",
    r"\bwithout\s*pay\b",
    r"\bno\s*pay\b",
    r"\b0\s*salary\b",
    r"\bzero\s*salary\b",
    r"\bequity\s*only\b",
    r"\bequity-only\b",
    r"\bexpenses\s*only\b",
    r"\breimbursement\s*only\b",
    r"\bcertificate\s*only\b",
    r"\buncompensated\b",
    r"\bcommission\s*only\b",
    r"\bperformance\s*based\s*only\b",
    r"\bincentive\s*only\b",
    r"\bincentives\s*only\b",
    r"\bnon-paid\b",
    r"\bnon\s*paid\b",
    r"\bnot\s*paid\b",
    r"\bfree\s*internship\b",
    r"(?:₹|\$|rs\.?|inr)\s*0\b",
    r"\b0\s*/\s*(?:month|mo|week|annum|year|yr)\b",
]

TARGET_ROLE_TIERS = {
    1: "GenAI Engineer / Developer",
    2: "AI Engineer / Developer",
    3: "AI Agent / Agentic AI",
}

EXCLUDED_ROLES = EXCLUDE_PATTERNS + SENIOR_PATTERNS


def is_excluded_company(company_name: str) -> bool:
    """Checks config/excluded.txt to prevent resurfaced or manually excluded employers."""
    if not company_name:
        return False
    comp_low = company_name.strip().lower()
    for ex in load_excluded_companies():
        if ex == comp_low:
            return True
        if len(ex) >= 5 and ex in comp_low:
            return True
    return False


def is_unpaid_role(text: str = "", title: str = "", salary: str = "") -> bool:
    """Returns True if the role matches any unpaid, volunteer, zero-stipend, or pro-bono patterns."""
    combined = f"{salary} {text} {title}".lower()
    return any(re.search(pat, combined) for pat in UNPAID_PATTERNS)


def is_internship(title: str, desc: str = "", url: str = "", source: str = "") -> bool:
    """Returns True if the role is eligible (Internshala/Wellfound entry-level or internship)."""
    src = source.lower()
    if src in ("internshala", "wellfound") or "/internship/" in url.lower():
        return True
    combined = f"{title} {desc}".lower()
    return any(re.search(pat, combined) for pat in INTERNSHIP_PATTERNS)


def classify_role(title: str, desc: str = "", url: str = "", source: str = "") -> Tuple[Optional[int], Optional[str], bool]:
    """
    Classifies a job title into Tier 1, 2, or 3 priority target while enforcing
    strict compensation, seniority/experience, non-engineering, and stack-fit filters.
    """
    if not title:
        return None, None, False

    t = title.strip().lower()
    combined = f"{t} {desc.lower()}"

    if is_unpaid_role(text=desc, title=t):
        return None, "Excluded: unpaid role excluded by candidate policy", False

    for sen in SENIOR_PATTERNS:
        if re.search(sen, t):
            return None, f"Excluded: senior level ({sen})", False

    for exp_pat in EXPERIENCE_MISMATCH_PATTERNS:
        if re.search(exp_pat, combined):
            return None, f"Excluded: requires 2+ YoE ({exp_pat})", False

    for ex in EXCLUDE_PATTERNS:
        if re.search(ex, t):
            return None, f"Excluded: non-target role ({ex})", False

    for stack_pat in UNMATCHED_STACK_PATTERNS:
        if re.search(stack_pat, t):
            return None, f"Excluded: unmatched stack ({stack_pat})", False

    if not is_internship(title, desc, url, source):
        return None, "Excluded: regular job (policy: internships only)", False

    for pat in TIER_1_PATTERNS:
        if re.search(pat, t):
            return 1, "GenAI Engineer / Developer", True

    for pat in TIER_3_PATTERNS:
        if re.search(pat, t):
            return 3, "AI Agent / Agentic AI", True

    for pat in TIER_2_PATTERNS:
        if re.search(pat, t):
            return 2, "AI Engineer / Developer", True

    return None, "Not in target priority list", False


def score_role_relevance(title: str, desc: str = "", company: str = "") -> int:
    """Computes a relevance score prioritizing GenAI/Agentic/FastAPI/Python roles over generic web/agencies."""
    combined = f"{title} {desc}".lower()
    t = (title or "").lower()
    c = (company or "").lower()
    score = 0

    if any(re.search(p, t) for p in TIER_1_PATTERNS):
        score += 30
    elif any(re.search(p, t) for p in TIER_3_PATTERNS):
        score += 25
    elif any(re.search(r"\b(ai|ml|python|backend|fastapi)\b", t) for _ in [0]):
        score += 18

    for kw, pts in (
        ("fastapi", 8), ("langgraph", 8), ("langchain", 6), ("rag", 8),
        ("llm", 7), ("genai", 8), ("agentic", 8), ("faiss", 6),
        ("python", 6), ("postgresql", 4), ("docker", 4), ("backend", 5),
        ("react", 3), ("full stack", 4), ("full-stack", 4),
    ):
        if kw in combined:
            score += pts

    # Slightly deprioritize third-party manpower/consultancies vs product teams
    if any(a in c for a in ("manpower", "placement", "consultancy", "head hunter", "staffing", "recruit")):
        score -= 8

    return score


def is_target_role(title: str, desc: str = "", url: str = "", source: str = "") -> bool:
    """Returns True if the role matches Tier 1, Tier 2, or Tier 3 priority targets."""
    _, _, ok = classify_role(title, desc, url, source)
    return ok
