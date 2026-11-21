#!/usr/bin/env python3
"""
job_discovery.py - step 1 of the job-hunt pipeline: discover -> dedupe -> score.

Sources: Greenhouse, Lever, Ashby  (public JSON APIs, per-company board slugs)
         We Work Remotely           (public RSS feeds, no auth)
         Himalayas                  (public JSON API, paginated, filterable)

Setup:   pip install requests groq          (groq only needed for --llm)
         export GROQ_API_KEY=...            (only for --llm)

Usage:   python job_discovery.py add <any Greenhouse/Lever/Ashby job or board URL>
         python job_discovery.py check      # which board slugs actually resolve
         python job_discovery.py run        # keyword-score only (free, instant)
         python job_discovery.py run --llm  # + LLM re-score of the top keyword hits

Files:   boards.json        boards to poll (edit / use `add`)
         master_resume.txt  your master resume (plain text)
         excluded.txt       companies already covered - never resurfaced
         jobs.db            SQLite dedupe store (created on first run)
"""
import argparse
import csv
import html
import json
import os
import re
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE = Path(__file__).resolve().parent
from src.core.classifier import is_unpaid_role
DB_PATH = BASE / "jobs.db"
BOARDS_PATH = BASE / "boards.json"
RESUME_PATH = BASE / "master_resume.txt"
EXCLUDED_PATH = BASE / "excluded.txt"

# Placeholder slugs from memory - run `check` to see which resolve. Big-company boards
# rarely have India interns; the real yield comes from startups you add with `add <url>`.
DEFAULT_BOARDS = {
    "wellfound": ["python-developer", "ai-engineer", "machine-learning-engineer"],
    "internshala": ["artificial-intelligence-ai-internship", "machine-learning-internship", "python-django-internship"],
    "greenhouse": ["anthropic", "databricks"],
    "lever": ["mistral", "palantir"],
    "ashby": ["openai", "cohere", "elevenlabs"],
    "wwr": ["remote-programming-jobs", "remote-back-end-programming-jobs",
            "remote-full-stack-programming-jobs"],
    "himalayas": ["artificial-intelligence,machine-learning,python,software-engineering"],
}


# ---------------------------------------------------------------- filters
ROLE_RE = re.compile(
    r"\b(ai|ml|llm|genai|gen ai|generative|machine learning|nlp|rag|agent|agents|agentic|"
    r"python|backend|back-end|software|applied)\b", re.I)
LEVEL_RE = re.compile(
    r"\b(intern|interns|internship|trainee|apprentice|fresher|graduate|junior|entry[- ]level|"
    r"associate|sde[- ]?1|new grad|early career)\b", re.I)
SENIOR_RE = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|manager|director|head|vp|architect)\b", re.I)

INDIA_RE = re.compile(
    r"\b(india|bengaluru|bangalore|hyderabad|mumbai|pune|delhi|noida|gurgaon|gurugram|"
    r"chennai|jaipur|kolkata|ahmedabad)\b", re.I)
REMOTE_RE = re.compile(r"\b(remote|anywhere|worldwide|global|apac|distributed)\b", re.I)
RESTRICT_RE = re.compile(
    r"\b(us|usa|u\.s\.|united states|san francisco|sf|new york|nyc|seattle|boston|austin|chicago|los angeles|"
    r"california|canada|toronto|vancouver|uk|london|united kingdom|europe|eu|emea|germany|berlin|france|paris|"
    r"brazil|latam|mexico|japan|tokyo|singapore|australia|sydney|ireland|dublin|netherlands|amsterdam)\b", re.I)

# JD says you must be in / authorised for the US -> not reachable from India
AUTH_RE = re.compile(
    r"(u\.?s\.? citizen|authori[sz]ed to work in the (united states|u\.?s)|"
    r"must (reside|be located|be based) in the (u\.?s|united states)|security clearance|"
    r"work authori[sz]ation in the (united states|us))", re.I)

# unpaid / pay-to-play / training-mill signals (surfaced as a note, not auto-skipped)
FLAG_RE = re.compile(
    r"\b(unpaid|no stipend|revenue[- ]partnership|registration fee|performance[- ]based stipend)\b",
    re.I)

# ---------------------------------------------------------------- skills vocabulary
# Case-insensitive unless wrapped in (?-i:...). "Owned" skills = vocab terms found in
# master_resume.txt, so the skill list can never drift from the resume.
# NOTE: "(in progress)" items in the resume still count as owned in keyword mode;
# the --llm pass is stricter about that.
VOCAB = {
    "python": r"python",
    "fastapi": r"fast\s?api",
    "flask": r"flask",
    "django": r"django",
    "rest/apis": r"restful|rest\s+apis?|(?-i:APIs?)",
    "sql": r"sql|postgres(?:ql)?|mysql|sqlite|sqlalchemy",
    "sqlalchemy": r"sqlalchemy",
    "jwt/auth": r"jwt|json web tokens?|oauth",
    "testing": r"pytest|unit tests?|unit testing",
    "docker": r"docker|containeri[sz]",
    "kubernetes": r"kubernetes|k8s",
    "git": r"(?-i:Git)(?:Hub|Lab)?",
    "ci/cd": r"ci/cd|github actions",
    "gcp": r"gcp|google cloud|cloud run",
    "aws": r"(?-i:AWS)|amazon web services",
    "azure": r"azure",
    "firebase": r"firebase",
    "llm": r"llms?|large language models?",
    "prompt engineering": r"prompt(?:ing)?\s+(?:engineering|design)",
    "rag": r"(?-i:RAG)|retrieval[- ]augmented",
    "vector search": r"vector\s+(?:databases?|dbs?|stores?|search)|faiss|pinecone|chroma(?:db)?|"
                     r"weaviate|qdrant|pgvector|milvus",
    "embeddings": r"embeddings?|sentence[- ]transformers?",
    "reranking": r"rerank(?:ing|er|ers)?|cross[- ]encoders?",
    "langchain": r"langchain",
    "langgraph": r"langgraph",
    "llamaindex": r"llama[- ]?index",
    "agents": r"agents?|agentic|multi[- ]agents?",
    "tool calling": r"tool[- ]?(?:calling|use)|function[- ]?calling",
    "mcp": r"(?-i:MCP)|model context protocol",
    "openai api": r"openai",
    "groq": r"groq",
    "claude/anthropic": r"claude|anthropic",
    "huggingface": r"hugging\s?face|transformers",
    "fine-tuning": r"fine[- ]?tun(?:e|ing|ed)|lora|qlora|peft",
    "pytorch": r"pytorch",
    "tensorflow": r"tensorflow",
    "scikit-learn": r"scikit[- ]learn|sklearn",
    "pandas": r"pandas",
    "numpy": r"numpy",
    "nlp": r"(?-i:NLP)|natural language processing",
    "computer vision": r"computer vision|opencv",
    "react": r"(?-i:React)(?:\.?js)?",
    "typescript": r"typescript",
    "javascript": r"javascript|node\.?js",
    "nextjs": r"next\.?js",
    "mongodb": r"mongo(?:db)?",
    "redis": r"redis",
    "kafka": r"kafka",
    "async": r"asyncio|async(?:hronous)?\s+(?:python|programming)",
    "microservices": r"microservices?",
    "observability/evals": r"langfuse|observability|evals?\b|evaluation (?:framework|pipeline)s?",
    "streamlit": r"streamlit",
    "n8n/zapier": r"n8n|zapier",
}
_VOCAB_RE = {k: re.compile(rf"(?<!\w)(?:{p})(?!\w)", re.I) for k, p in VOCAB.items()}


def skills_in(text):
    return {k for k, rx in _VOCAB_RE.items() if rx.search(text or "")}


# ---------------------------------------------------------------- helpers
def strip_html(s):
    s = html.unescape(s or "")                       # Greenhouse ships escaped HTML
    s = re.sub(r"<(script|style).*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def load_excluded():
    if not EXCLUDED_PATH.exists():
        return set()
    out = set()
    for line in EXCLUDED_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # "Klarixa AI (Pharmatek Solutions)" -> both names
        parts = [re.sub(r"\(.*?\)", "", line)] + re.findall(r"\((.*?)\)", line)
        for p in parts:
            p = re.sub(r"\b(private limited|pvt\.? ltd\.?|limited|llp|p\.l\.)\b", "", p, flags=re.I)
            if norm(p):
                out.add(norm(p))
    return out


def is_excluded(company, excluded):
    c = norm(company)
    # short names (e.g. "JLL") need an exact match; longer ones may be contained in the slug
    return any(c == e or (len(e) >= 5 and e in c) for e in excluded)


def get(url, **kw):
    for i in range(3):
        try:
            r = requests.get(url, timeout=20, headers={"User-Agent": "job-discovery/0.1 (personal use)"}, **kw)
            if r.status_code == 200:
                return r
            if r.status_code == 404:
                raise FileNotFoundError(url)
        except requests.RequestException:
            pass
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"request failed after retries: {url}")


# ---------------------------------------------------------------- ATS fetchers
def fetch_greenhouse(slug):
    r = get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", params={"content": "true"})
    for j in r.json().get("jobs", []):
        yield dict(ext_id=str(j.get("id")), title=j.get("title", ""),
                   location=(j.get("location") or {}).get("name", ""),
                   url=j.get("absolute_url", ""), posted=(j.get("updated_at") or "")[:10],
                   is_remote=False, employment="", desc=strip_html(j.get("content", "")))


def fetch_lever(slug):
    r = get(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"})
    for j in r.json():
        cats = j.get("categories") or {}
        parts = [j.get("descriptionPlain", "")]
        parts += [f"{l.get('text', '')} {strip_html(l.get('content', ''))}" for l in j.get("lists", [])]
        parts.append(j.get("additionalPlain", ""))
        ts = j.get("createdAt")
        posted = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).date().isoformat() if ts else ""
        yield dict(ext_id=str(j.get("id")), title=j.get("text", ""), location=cats.get("location", "") or "",
                   url=j.get("hostedUrl", ""), posted=posted,
                   is_remote=(j.get("workplaceType") == "remote"),
                   employment=cats.get("commitment", "") or "", desc=" ".join(parts))


def fetch_ashby(slug):
    r = get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    for j in r.json().get("jobs", []):
        if j.get("isListed") is False:
            continue
        yield dict(ext_id=str(j.get("id")), title=j.get("title", ""), location=j.get("location", "") or "",
                   url=j.get("jobUrl") or j.get("applyUrl", ""), posted=(j.get("publishedAt") or "")[:10],
                   is_remote=bool(j.get("isRemote")), employment=j.get("employmentType", "") or "",
                   desc=j.get("descriptionPlain") or strip_html(j.get("descriptionHtml", "")))


FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby,
            "wwr": None, "himalayas": None}  # replaced below after function defs


def fetch_wwr(category):
    """Parse a We Work Remotely RSS category feed.
    Category examples: remote-programming-jobs, remote-back-end-programming-jobs.
    The <title> is usually 'Company: Role Title'.
    """
    url = f"https://weworkremotely.com/categories/{category}.rss"
    r = get(url)
    root = ET.fromstring(r.text)
    for item in root.iter("item"):
        title_text = (item.findtext("title") or "").strip()
        # WWR titles are usually "Company: Role" — split on first colon
        if ": " in title_text:
            company_name, job_title = title_text.split(": ", 1)
        else:
            company_name, job_title = "Unknown", title_text
        region = (item.findtext("region") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        # Parse pubDate like "Sun, 28 Sep 2026 12:00:00 +0000" -> YYYY-MM-DD
        posted = ""
        if pub_date:
            try:
                posted = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %z").date().isoformat()
            except ValueError:
                posted = pub_date[:10]
        desc_html = (item.findtext("description") or "")
        desc = strip_html(desc_html)
        # Generate a stable ext_id from the link
        ext_id = norm(link) or norm(title_text)
        yield dict(ext_id=ext_id, title=job_title, location=region,
                   url=link, posted=posted, is_remote=True,
                   employment="", desc=desc, company_name=company_name)


def fetch_himalayas(categories_csv):
    """Fetch jobs from Himalayas public JSON API.
    categories_csv: comma-separated category slugs, e.g. 'artificial-intelligence,machine-learning'
    Paginates up to 200 jobs, filtering for entry-level and mid-level seniority.
    """
    base = "https://himalayas.app/jobs/api"
    offset = 0
    limit = 50
    max_results = 200  # cap to avoid hammering
    fetched = 0
    while fetched < max_results:
        params = {
            "limit": limit,
            "offset": offset,
            "categories": categories_csv,
        }
        try:
            r = get(base + "?" + "&".join(f"{k}={v}" for k, v in params.items()))
            data = r.json()
        except Exception:
            break
        jobs = data.get("jobs", [])
        if not jobs:
            break
        for j in jobs:
            seniority = j.get("seniority") or []
            if isinstance(seniority, str):
                seniority = [seniority]
            # Only entry-level and mid-level
            seniority_ok = not seniority or any(
                s.lower() in ("entry-level", "mid-level", "intern", "internship", "junior")
                for s in seniority
            )
            if not seniority_ok:
                continue
            desc = j.get("description") or j.get("excerpt") or ""
            desc = strip_html(desc)
            raw_pub = j.get("pubDate")
            if isinstance(raw_pub, (int, float)):
                try:
                    ts = raw_pub / 1000 if raw_pub > 1e11 else raw_pub
                    posted = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
                except Exception:
                    posted = ""
            else:
                posted = str(raw_pub or "")[:10]
            loc_restrictions = j.get("locationRestrictions") or []
            location = ", ".join(loc_restrictions) if loc_restrictions else "Worldwide"
            app_link = j.get("applicationLink") or ""
            company_name = j.get("companyName") or "Unknown"
            ext_id = j.get("guid") or norm(f"{company_name}{j.get('title','')}")
            yield dict(ext_id=ext_id, title=j.get("title", ""), location=location,
                       url=app_link, posted=posted, is_remote=True,
                       employment=j.get("employmentType", "") or "",
                       desc=desc, company_name=company_name)
            fetched += 1
            if fetched >= max_results:
                break
        offset += limit
        total = data.get("totalCount", 0)
        if offset >= total:
            break


def fetch_internshala(category_slug, max_pages=5):
    """Fetch public internship listings from Internshala for freshers and students across multiple pages."""
    from bs4 import BeautifulSoup
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    seen_ids = set()
    for page_num in range(1, max_pages + 1):
        if page_num == 1:
            url = f"https://internshala.com/internships/{category_slug}/"
        else:
            url = f"https://internshala.com/internships/{category_slug}/page-{page_num}/"

        try:
            r = requests.get(url, headers=headers, timeout=12)
            if r.status_code != 200:
                break
        except Exception:
            break

        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.find_all("div", class_="individual_internship")
        if not cards:
            break

        page_yielded = 0
        for c in cards:
            title_el = c.find("a", class_="job-title-href") or c.find("h3", class_="job-internship-name")
            if not title_el:
                continue
            title = title_el.text.strip()
            comp_el = c.find("p", class_="company-name") or c.find("a", class_="link_display_like_text")
            company = comp_el.text.strip() if comp_el else "Unknown"
            loc_el = c.find("a", class_="location_link") or c.find("span", class_="location")
            location = loc_el.text.strip() if loc_el else "Work from home"
            link_el = c.find("a", class_="job-title-href")
            link = "https://internshala.com" + link_el["href"] if link_el and "href" in link_el.attrs else ""
            stipend_el = c.find("span", class_="stipend")
            stipend = stipend_el.text.strip() if stipend_el else ""
            # Candidate policy: Strictly NEVER fetch or surface unpaid internships
            if is_unpaid_role(text=stipend, title=title, salary=stipend):
                continue
            ext_id = link_el["href"].split("/")[-1] if link_el and "href" in link_el.attrs else norm(f"{company}{title}")

            if ext_id in seen_ids:
                continue
            seen_ids.add(ext_id)
            page_yielded += 1

            yield dict(
                ext_id=ext_id,
                title=title,
                location=location,
                url=link,
                posted=date.today().isoformat(),
                is_remote=("work from home" in location.lower()),
                employment="internship",
                desc=f"{title} internship at {company}. Location: {location}. Stipend: {stipend}",
                company_name=company
            )

        if page_yielded == 0:
            break


def fetch_wellfound(role_or_slug):
    """Fetch startup job listings from Wellfound (AngelList) for AI, ML, and Python roles."""
    from bs4 import BeautifulSoup

    # Handle role slug, location slug, or company jobs
    clean_slug = role_or_slug.strip().strip("/")
    if clean_slug.startswith("company/"):
        url = f"https://wellfound.com/{clean_slug}/jobs"
    elif clean_slug.startswith("location/"):
        url = f"https://wellfound.com/{clean_slug}"
    elif clean_slug.startswith("role/"):
        url = f"https://wellfound.com/{clean_slug}"
    else:
        url = f"https://wellfound.com/role/{clean_slug}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            return
        html_text = r.text
    except Exception as e:
        print(f"  ! Wellfound fetch error for {role_or_slug}: {e}")
        return

    soup = BeautifulSoup(html_text, "html.parser")
    job_links = soup.find_all("a", href=re.compile(r"/jobs/\d+"))
    seen_urls = set()

    for a in job_links:
        href = a.get("href", "")
        if not href or href in seen_urls:
            continue
        seen_urls.add(href)

        full_url = f"https://wellfound.com{href}" if not href.startswith("http") else href
        title = a.get_text(strip=True)
        m = re.search(r"/jobs/(\d+)", href)
        ext_id = m.group(1) if m else href.split("/")[-1]

        # Extract company name from parent company card
        card = a.find_parent("div", class_=re.compile(r"border-gray-400"))
        company = "Unknown"
        if card:
            comp_links = card.find_all("a", href=re.compile(r"/company/"))
            for cl in comp_links:
                t = cl.get_text(strip=True)
                if t:
                    company = t
                    break

        # Extract metadata from row
        row = a.find_parent("div", class_=re.compile(r"min-h-\[50px\]"))
        row_text = row.get_text(separator=" | ", strip=True) if row else ""

        # Skip positions requiring 5+ years of experience
        if re.search(r"\b([5-9]|\d{2})\+?\s*years?\s*of\s*exp", row_text, re.I):
            continue

        is_remote = any(k in row_text.lower() for k in ["remote", "work from home", "anywhere"])

        # Detect location
        location = "Remote" if is_remote else "Worldwide"
        parts = [p.strip() for p in row_text.split("|")]
        for p in parts:
            if any(c in p.lower() for c in ["bengaluru", "bangalore", "delhi", "noida", "gurgaon", "gurugram", "mumbai", "hyderabad", "pune", "chennai", "jaipur", "india"]):
                location = p
                break
            elif any(c in p.lower() for c in ["san francisco", "new york", "london", "austin", "seattle"]):
                location = p

        is_intern = any(k in title.lower() or k in row_text.lower() for k in ["intern", "internship", "fresher", "trainee"])
        employment = "internship" if is_intern else "entry-level"

        desc = f"{title} at {company}. {row_text}"

        yield dict(
            ext_id=ext_id,
            title=title,
            location=location,
            url=full_url,
            posted=date.today().isoformat(),
            is_remote=is_remote,
            employment=employment,
            desc=desc,
            company_name=company
        )


# Update FETCHERS with the new sources
FETCHERS["wwr"] = fetch_wwr
FETCHERS["himalayas"] = fetch_himalayas
FETCHERS["internshala"] = fetch_internshala
FETCHERS["wellfound"] = fetch_wellfound


from target_roles import classify_role, is_target_role


def title_ok(title, employment="", intern_only=True):
    tier, cat, is_target = classify_role(title)
    return is_target


def location_ok(loc, is_remote):
    loc = loc or ""
    if INDIA_RE.search(loc):
        return True
    if re.search(r"\b(anywhere|worldwide|global)\b", loc, re.I):
        return True
    if RESTRICT_RE.search(loc):
        return False
    return bool(is_remote or REMOTE_RE.search(loc))


def kw_match(title, desc, my_skills):
    jd = skills_in(f"{title} {desc}")
    have = jd & my_skills
    if len(jd) >= 1:
        score = round(100 * len(have) / len(jd))
    elif ROLE_RE.search(title):
        score = 75  # Direct role keyword match in title
    else:
        score = 0
    return score, sorted(have), sorted(jd - my_skills)


def llm_match(job, resume):
    """Stricter re-score via Groq. Returns dict or None on any failure."""
    try:
        from groq import Groq
        client = Groq()
        prompt = (
            "You are a strict ATS-style matcher. Compare the job description to the candidate resume.\n"
            "Score ONLY what the resume actually evidences; never assume skills. Items marked "
            "'(in progress)' count as partial.\n"
            'Return ONLY JSON: {"score": 0-100, "missing_keywords": [..], "strengths": [..], '
            '"red_flags": [..], "apply": true|false}\n'
            "red_flags = unpaid, pay-to-play, US-only authorization, wildly senior requirements.\n\n"
            f"RESUME:\n{resume[:6000]}\n\nJOB: {job['title']} @ {job['company']} ({job['location']})\n"
            f"{job['desc'][:6000]}")
        resp = client.chat.completions.create(
            model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"), temperature=0,
            response_format={"type": "json_object"}, messages=[{"role": "user", "content": prompt}])
        data = json.loads(resp.choices[0].message.content)
        data["score"] = int(data.get("score", 0))
        return data
    except Exception as e:  # noqa: BLE001 - any failure just falls back to keyword score
        print(f"  ! LLM match failed for {job['company']} / {job['title']}: {e}")
        return None


# ---------------------------------------------------------------- storage
def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS jobs(
        id TEXT PRIMARY KEY, source TEXT, company TEXT, title TEXT, location TEXT, url TEXT,
        posted TEXT, first_seen TEXT, kw_score INTEGER, llm_score INTEGER,
        missing TEXT, notes TEXT, status TEXT, target_tier INTEGER, target_category TEXT)""")
    cur = con.cursor()
    cols = [r[1] for r in cur.execute("PRAGMA table_info(jobs)").fetchall()]
    if "target_tier" not in cols:
        cur.execute("ALTER TABLE jobs ADD COLUMN target_tier INTEGER")
    if "target_category" not in cols:
        cur.execute("ALTER TABLE jobs ADD COLUMN target_category TEXT")
    con.commit()
    return con


def load_boards():
    if not BOARDS_PATH.exists():
        BOARDS_PATH.write_text(json.dumps(DEFAULT_BOARDS, indent=2))
    return json.loads(BOARDS_PATH.read_text())


# ---------------------------------------------------------------- commands
def cmd_run(args):
    boards, con = load_boards(), init_db()
    resume = RESUME_PATH.read_text(encoding="utf-8")
    my_skills = skills_in(resume)
    excluded = load_excluded()
    seen_ids = {r[0] for r in con.execute("SELECT id FROM jobs")}
    seen_urls = {r[0] for r in con.execute("SELECT url FROM jobs")}
    stats = dict(fetched=0, passed_filters=0, excluded=0, dupes=0, us_only=0, new=0, errors=0)
    fresh = []

    print(f"Resume skills detected ({len(my_skills)}): {', '.join(sorted(my_skills))}\n")
    for source, slugs in boards.items():
        for slug in slugs:
            if source in ("greenhouse", "lever", "ashby") and is_excluded(slug, excluded):
                stats["excluded"] += 1
                continue
            try:
                jobs = list(FETCHERS[source](slug))
            except FileNotFoundError:
                print(f"  ! {source}/{slug}: board not found (run `check`)")
                stats["errors"] += 1
                continue
            except Exception as e:  # noqa: BLE001
                print(f"  ! {source}/{slug}: {e}")
                stats["errors"] += 1
                continue
            for j in jobs:
                stats["fetched"] += 1
                # WWR and Himalayas provide company_name per job; ATS sources use slug
                company_name = j.pop("company_name", None) or slug
                # Check per-job company exclusion (important for aggregator sources)
                if is_excluded(company_name, excluded):
                    stats["excluded"] += 1
                    continue
                is_intern_mode = not getattr(args, "all_levels", False)
                if not (title_ok(j["title"], j["employment"], intern_only=is_intern_mode) and location_ok(j["location"], j["is_remote"])):
                    continue
                stats["passed_filters"] += 1
                jid = f"{source}:{j['ext_id']}"
                if jid in seen_ids or j.get("url") in seen_urls:
                    stats["dupes"] += 1
                    continue
                seen_ids.add(jid)
                if j.get("url"):
                    seen_urls.add(j["url"])
                j.update(id=jid, source=source, company=company_name)
                notes = []
                status = "new"
                if AUTH_RE.search(j["desc"]):
                    status, notes = "skipped_us_only", ["US work authorization required"]
                if FLAG_RE.search(j["desc"]):
                    notes.append("possible unpaid / pay-to-play - read carefully")
                score, have, missing = kw_match(j["title"], j["desc"], my_skills)
                tier, cat, is_target = classify_role(j["title"])
                if not is_target:
                    status = "non_target_role"
                elif status == "new" and score < args.min_score:
                    status = "low_score"
                j.update(kw=score, llm=None, have=have, missing=missing, notes=notes, status=status,
                         target_tier=tier, target_category=cat)
                con.execute("""INSERT INTO jobs (id, source, company, title, location, url, posted,
                                                 first_seen, kw_score, llm_score, missing, notes, status,
                                                 target_tier, target_category)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (jid, source, company_name, j["title"], j["location"], j["url"], j["posted"],
                             date.today().isoformat(), score, None, ", ".join(missing), "; ".join(notes), status,
                             tier, cat))
                if status == "new":
                    stats["new"] += 1
                    fresh.append(j)
    con.commit()

    if args.llm and fresh:
        fresh.sort(key=lambda x: -x["kw"])
        print(f"LLM re-scoring top {min(args.llm_top, len(fresh))} of {len(fresh)} new jobs...")
        for j in fresh[:args.llm_top]:
            res = llm_match(j, resume)
            time.sleep(2)  # be gentle with the free tier
            if not res:
                continue
            j["llm"] = res["score"]
            j["missing"] = res.get("missing_keywords") or j["missing"]
            j["notes"] += [f"red flag: {x}" for x in res.get("red_flags", [])]
            status = "new" if (res["score"] >= args.min_score and res.get("apply", True)) else "low_score"
            con.execute("UPDATE jobs SET llm_score=?, missing=?, notes=?, status=? WHERE id=?",
                        (res["score"], ", ".join(map(str, j["missing"])), "; ".join(j["notes"]), status, j["id"]))
            j["status"] = status
        con.commit()

    keep = [j for j in fresh if j["status"] == "new"]
    keep.sort(key=lambda x: -(x["llm"] if x["llm"] is not None else x["kw"]))

    out = BASE / f"new_jobs_{date.today().isoformat()}.csv"
    if keep:  # never overwrite an earlier same-day CSV with an empty one
        new_file = not out.exists()
        with open(out, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(["score", "company", "title", "location", "url", "posted", "missing", "notes"])
            for j in keep:
                w.writerow([j["llm"] if j["llm"] is not None else j["kw"], j["company"], j["title"],
                            j["location"], j["url"], j["posted"], ", ".join(map(str, j["missing"])), "; ".join(j["notes"])])

    print(f"\nfetched={stats['fetched']} passed_filters={stats['passed_filters']} "
          f"dupes={stats['dupes']} excluded_boards={stats['excluded']} us_only={stats['us_only']} "
          f"new={stats['new']} kept={len(keep)} errors={stats['errors']}")
    if not keep:
        print("Nothing new above the threshold today.")
    for j in keep[:args.top]:
        s = j["llm"] if j["llm"] is not None else j["kw"]
        print(f"\n[{s:>3}] {j['company']} - {j['title']} ({j['location'] or 'n/a'})\n      {j['url']}")
        if j["missing"]:
            print(f"      missing: {', '.join(map(str, j['missing'][:8]))}")
        for n in j["notes"]:
            print(f"      ! {n}")
    if keep:
        print(f"\nSaved {len(keep)} jobs -> {out.name}")


def cmd_check(_):
    for source, slugs in load_boards().items():
        for slug in slugs:
            try:
                n = 0
                for _ in FETCHERS[source](slug):
                    n += 1
                    if n >= 5:  # don't fetch everything, just confirm the source works
                        break
                suffix = "5+" if n >= 5 else str(n)
                print(f"OK         {source}/{slug} ({suffix} jobs)")
            except FileNotFoundError:
                print(f"NOT FOUND  {source}/{slug}")
            except Exception as e:  # noqa: BLE001
                print(f"ERROR      {source}/{slug}: {e}")


def parse_board_url(url):
    u = urlparse(url)
    host, parts = u.netloc.lower(), [p for p in u.path.split("/") if p]
    if "greenhouse.io" in host:
        if parts and parts[0] == "embed":
            qs = parse_qs(u.query).get("for")
            return ("greenhouse", qs[0]) if qs else (None, None)
        return ("greenhouse", parts[0]) if parts else (None, None)
    if host.endswith("lever.co") and parts:
        return "lever", parts[0]
    if host.endswith("ashbyhq.com") and parts:
        return "ashby", parts[0]
    if "wellfound.com" in host:
        if "role" in parts:
            idx = parts.index("role")
            if idx + 1 < len(parts):
                return "wellfound", parts[idx + 1]
        if "company" in parts:
            idx = parts.index("company")
            if idx + 1 < len(parts):
                return "wellfound", f"company/{parts[idx + 1]}"
        if "location" in parts:
            idx = parts.index("location")
            if idx + 1 < len(parts):
                return "wellfound", f"location/{parts[idx + 1]}"
        if parts:
            return "wellfound", parts[0]
        return "wellfound", "python-developer"
    if "internshala.com" in host:
        if "internships" in parts:
            idx = parts.index("internships")
            if idx + 1 < len(parts):
                return "internshala", parts[idx + 1]
        return "internshala", parts[0] if parts else "artificial-intelligence-ai-internship"
    return None, None


def cmd_add(args):
    source, slug = parse_board_url(args.url)
    if not source:
        sys.exit("Not a supported job board URL (Greenhouse, Lever, Ashby, Wellfound, Internshala).")
    boards = load_boards()
    if slug in boards.setdefault(source, []):
        print(f"{source}/{slug} already tracked.")
        return
    boards[source].append(slug)
    BOARDS_PATH.write_text(json.dumps(boards, indent=2))
    print(f"Added {source}/{slug}. Run `check` to confirm it resolves.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--llm", action="store_true", help="re-score top keyword hits with Groq")
    r.add_argument("--llm-top", type=int, default=15)
    r.add_argument("--min-score", type=int, default=30)
    r.add_argument("--top", type=int, default=15, help="how many to print")
    r.add_argument("--all-levels", action="store_true", help="include mid-level roles (default is fresher/intern only)")
    r.set_defaults(fn=cmd_run)
    sub.add_parser("check").set_defaults(fn=cmd_check)
    a = sub.add_parser("add")
    a.add_argument("url")
    a.set_defaults(fn=cmd_add)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
