import re
from typing import Optional, Tuple

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
    r"\bprompt\s*engineering\b"
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
    r"\bcrewai\b"
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
    r"\bnode\.?js\b",
    r"\breact\b",
    r"\bdjango\b",
    r"\bfastapi\b",
    r"\bcomputer\s*science\b",
    r"\bml\s*engineer\b",
    r"\bml\s*developer\b",
    r"\bai\s*/\s*ml\b"
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
    r"\bfellowship\b"
]

EXCLUDE_PATTERNS = [
    r"\bfemale\b",
    r"\bvideo\b",
    r"\beditor\b",
    r"\bgrowth\b",
    r"\boperations\b",
    r"\btrainer\b",
    r"\bteacher\b",
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
    r"\baccountant\b"
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


def is_unpaid_role(text: str = "", title: str = "", salary: str = "") -> bool:
    """
    Candidate Policy: Strictly NEVER apply to unpaid work.
    Returns True if the role matches any unpaid, volunteer, zero-stipend, or pro-bono patterns.
    """
    combined = f"{salary} {text} {title}".lower()
    for pat in UNPAID_PATTERNS:
        if re.search(pat, combined):
            return True
    return False

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
    r"\barchitect\b"
]

TARGET_ROLE_TIERS = {
    1: "GenAI Engineer / Developer",
    2: "AI Engineer / Developer",
    3: "AI Agent / Agentic AI"
}

EXCLUDED_ROLES = EXCLUDE_PATTERNS + SENIOR_PATTERNS


def is_internship(title: str, desc: str = "", url: str = "", source: str = "") -> bool:
    """Returns True if the role is eligible (internship on Internshala, or non-senior developer on Wellfound)."""
    src = source.lower()
    if src in ("internshala", "wellfound") or "/internship/" in url.lower():
        return True
    combined = f"{title} {desc}".lower()
    for pat in INTERNSHIP_PATTERNS:
        if re.search(pat, combined):
            return True
    return False


def classify_role(title: str, desc: str = "", url: str = "", source: str = "") -> Tuple[Optional[int], Optional[str], bool]:
    """
    Classifies a job title into Tier 1, 2, or 3 priority target.

    Returns:
        (tier: int | None, category_name: str | None, is_target: bool)
    """
    if not title:
        return None, None, False

    t = title.strip().lower()

    # 0. Strict Unpaid / Volunteer Exclusion Filter (Never apply to unpaid work)
    if is_unpaid_role(text=desc, title=t):
        return None, "Excluded: unpaid role excluded by candidate policy", False

    # 1. Senior / Management Filter
    for sen in SENIOR_PATTERNS:
        if re.search(sen, t):
            return None, f"Excluded: senior level ({sen})", False

    # 2. Strict Exclusions (Negative Filter: non-engineering, sales, HR, marketing, etc.)
    for ex in EXCLUDE_PATTERNS:
        if re.search(ex, t):
            return None, f"Excluded: non-target role ({ex})", False

    # 3. Eligibility Filter
    if not is_internship(title, desc, url, source):
        return None, "Excluded: regular job (policy: internships only)", False

    # 4. Priority Tier 1: GenAI Engineer / Developer
    for pat in TIER_1_PATTERNS:
        if re.search(pat, t):
            return 1, "GenAI Engineer / Developer", True

    # 5. Priority Tier 3: AI Agent / Agentic AI
    for pat in TIER_3_PATTERNS:
        if re.search(pat, t):
            return 3, "AI Agent / Agentic AI", True

    # 6. Priority Tier 2: AI Engineer / Python / Backend / Full Stack Developer
    for pat in TIER_2_PATTERNS:
        if re.search(pat, t):
            return 2, "AI Engineer / Developer", True

    return None, "Not in target priority list", False


def is_target_role(title: str, desc: str = "", url: str = "", source: str = "") -> bool:
    """Returns True if the role matches Tier 1, Tier 2, or Tier 3 priority targets."""
    tier, _, ok = classify_role(title, desc, url, source)
    return ok
