import datetime
import sqlite3
from typing import Any, Dict, List, Optional, Tuple
from src.config import DB_PATH
from src.core.classifier import is_unpaid_role


def get_connection() -> sqlite3.Connection:
    """Returns a SQLite connection with Row factory."""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def get_platform_jobs(source: str, limit: int = 20, target_tiers: Tuple[int, ...] = (1, 2, 3)) -> List[Dict[str, Any]]:
    """
    Retrieves top N matching target roles (Tiers 1, 2, 3 only) for a specific platform.
    Ensures clean URL formatting, internship-only policy, and sorts by priority and scores.
    """
    con = get_connection()
    tier_placeholders = ",".join("?" for _ in target_tiers)
    
    query = f"""
        SELECT id, source, company, title, location, url, kw_score, llm_score, notes, status,
               target_tier, target_category
        FROM jobs
        WHERE source = ? 
          AND (target_tier IN ({tier_placeholders}) OR target_tier IS NULL)
          AND status IN ('staged_for_review', 'new', 'failed', 'login_required', 'low_score')
          AND status NOT IN ('non_target_role', 'unpaid_excluded', 'ineligible', 'expired')
          AND lower(COALESCE(notes, '')) NOT LIKE '%unpaid%'
          AND lower(COALESCE(notes, '')) NOT LIKE '%no stipend%'
          AND lower(COALESCE(notes, '')) NOT LIKE '%0 stipend%'
          AND lower(COALESCE(notes, '')) NOT LIKE '%zero stipend%'
          AND lower(COALESCE(notes, '')) NOT LIKE '%without stipend%'
          AND lower(COALESCE(notes, '')) NOT LIKE '%volunteer%'
          AND lower(COALESCE(notes, '')) NOT LIKE '%pro bono%'
          AND lower(COALESCE(notes, '')) NOT LIKE '%equity only%'
          AND lower(COALESCE(notes, '')) NOT LIKE '%without pay%'
          AND lower(COALESCE(notes, '')) NOT LIKE '%no pay%'
          AND lower(COALESCE(title, '')) NOT LIKE '%unpaid%'
          AND lower(COALESCE(title, '')) NOT LIKE '%volunteer%'
          AND (source = 'internshala' 
               OR source = 'wellfound'
               OR url LIKE '%/internship/%' 
               OR lower(title) LIKE '%intern%' 
               OR lower(title) LIKE '%trainee%' 
               OR lower(title) LIKE '%apprentice%' 
               OR lower(title) LIKE '%fellow%')
          AND (source != 'wellfound' OR (url LIKE '%wellfound.com/jobs/%' AND url NOT LIKE '%wellfound.com/company/%'))
        GROUP BY url
        ORDER BY 
            CASE WHEN status = 'new' THEN 1 WHEN status = 'failed' THEN 2 ELSE 3 END,
            CASE 
                WHEN lower(location) LIKE '%remote%' OR lower(location) LIKE '%worldwide%' OR lower(location) LIKE '%jaipur%' OR lower(location) LIKE '%anywhere%' THEN 1
                ELSE 2
            END ASC,
            posted DESC,
            target_tier ASC,
            COALESCE(llm_score, 0) DESC,
            COALESCE(kw_score, 0) DESC
        LIMIT ?
    """
    params = [source] + list(target_tiers) + [limit * 2]
    rows = con.execute(query, params).fetchall()
    
    valid_jobs = []
    for r in rows:
        job_dict = dict(r)
        if is_unpaid_role(text=job_dict.get("notes", ""), title=job_dict.get("title", "")):
            con.execute("UPDATE jobs SET status = 'unpaid_excluded' WHERE id = ?", (job_dict["id"],))
            continue
        valid_jobs.append(job_dict)
        if len(valid_jobs) >= limit:
            break
            
    con.commit()
    return valid_jobs


def update_job_status(job_id: str, status: str, url: Optional[str] = None) -> None:
    """Updates job status in database for the given ID and any matching URL rows."""
    con = get_connection()
    con.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
    if url and status in ("applied", "already_applied", "expired", "rejected", "ineligible"):
        con.execute("UPDATE jobs SET status = ? WHERE url = ? AND status != ?", (status, url, status))
    con.commit()


def get_stats() -> Dict[str, Any]:
    """Retrieves high-level pipeline metrics across all platforms and statuses."""
    con = get_connection()
    status_counts = dict(con.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status").fetchall())
    platform_counts = dict(con.execute("SELECT source, COUNT(*) FROM jobs GROUP BY source").fetchall())
    applied_by_platform = dict(con.execute("SELECT source, COUNT(*) FROM jobs WHERE status = 'applied' GROUP BY source").fetchall())
    tier_counts = dict(con.execute("SELECT target_tier, COUNT(*) FROM jobs WHERE target_tier IS NOT NULL GROUP BY target_tier").fetchall())

    return {
        "status_counts": status_counts,
        "platform_counts": platform_counts,
        "applied_by_platform": applied_by_platform,
        "tier_counts": tier_counts,
        "total_jobs": sum(status_counts.values())
    }


def seed_sample_jobs() -> None:
    """Ensures verified Target Roles (Tiers 1, 2, 3 - Internships Only) exist in database."""
    con = get_connection()
    today_slug = datetime.date.today().strftime("%Y%m%d")

    sample_target_jobs = [
        # Internshala - Verified Target Roles (Tiers 1, 2, 3 - Internships)
        ("internshala:manifest:agent", "internshala", "Manifest Hospitality", "AI Agent Development Intern", "Work from home", "https://internshala.com/internship/detail/ai-agent-development-internship-in-kolkata-at-manifest-hospitality1789717103", "₹15,000 - ₹25,000 / month", "Python, AI Agents, LLM Integration, LangChain", "new", 3, "AI Agent / Agentic AI Intern"),
        ("internshala:sankar:agent", "internshala", "Sankar Group", "AI Agent Development Intern", "Work from home", "https://internshala.com/internship/detail/work-from-home-ai-agent-development-internship-at-sankar-group1790534428", "₹15,000 - ₹25,000 / month", "Python, Autonomous Agents, LLMs, RAG", "new", 3, "AI Agent / Agentic AI Intern"),
        ("internshala:futurebound:ai", "internshala", "Future Bound Tech", "Artificial Intelligence Intern", "Work from home", "https://internshala.com/internship/detail/artificial-intelligence-ai-internship-in-andhra-pradesh-at-future-bound-tech1790492067", "₹12,000 - ₹20,000 / month", "Python, PyTorch, Transformers, Deep Learning", "new", 2, "AI Engineer / Applied AI Intern"),
        ("internshala:dsc:automation", "internshala", "DSC Pipes and Tubes", "AI Automation Intern", "Work from home", "https://internshala.com/internship/detail/ai-automation-internship-in-chennai-at-dsc-pipes-and-tubes-private-limited1790162760", "₹15,000 - ₹22,000 / month", "Python, LLM Prompting, Agentic Automation, FastAPI", "new", 3, "AI Agent / Agentic AI Intern"),
        ("internshala:soulstarr:founding", "internshala", "Soulstarr AI", "Founding AI Engineer Intern", "Work from home", "https://internshala.com/internship/detail/work-from-home-founding-ai-engineer-internship-at-soulstarr-ai1790419861", "₹20,000 - ₹35,000 / month", "Python, LangGraph, Multi-Agent Systems, RAG, FastAPI", "new", 1, "GenAI Engineer Intern"),
        ("internshala:nbs:ai", "internshala", "New Business Strategies Corporation", "Artificial Intelligence Intern", "Work from home", "https://internshala.com/internship/detail/work-from-home-artificial-intelligence-ai-internship-at-new-business-strategies-corporation1790537644", "₹15,000 - ₹25,000 / month", "Python, Machine Learning, Deep Learning, REST APIs", "new", 2, "AI Engineer / Applied AI Intern"),
        ("internshala:startupcfos:agent", "internshala", "Startupcfos", "AI Agent Development Intern", "Work from home", "https://internshala.com/internship/detail/ai-agent-development-internship-in-mumbai-at-startupcfos1790512533", "₹18,000 - ₹28,000 / month", "Python, LangChain, OpenAI, LLM Agents, Automation", "new", 3, "AI Agent / Agentic AI Intern"),
        ("internshala:trippleone:ai", "internshala", "Tripple One Solutions", "Artificial Intelligence Intern", "Work from home", "https://internshala.com/internship/detail/work-from-home-artificial-intelligence-ai-internship-at-tripple-one-solutions1790485261", "₹12,000 - ₹20,000 / month", "Python, TensorFlow, Scikit-learn, Data Analysis", "new", 2, "AI Engineer / Applied AI Intern"),

        # Wellfound - Real Scraped Target Roles (Tiers 1, 2, 3)
        ("wellfound:4867065", "wellfound", "Ink'd", "AI / Backend Engineer – Remote", "Remote (Everywhere)", "https://wellfound.com/jobs/4867065-ai-backend-engineer-remote", "$18,000 - $30,000 Annually", "Python, FastAPI, LLMs, RAG, REST APIs", "new", 1, "GenAI Engineer / Developer"),
        ("wellfound:4868453", "wellfound", "ISFY", "Backend Developer (Claude-powered, Remote)", "Remote (Everywhere)", "https://wellfound.com/jobs/4868453-backend-developer-claude-powered-remote", "$18,000 - $30,000 Annually", "Python, Claude API, LLMs, Automation, FastAPI", "new", 1, "GenAI Engineer / Developer"),
        ("wellfound:4867200", "wellfound", "Helfen Company", "AI Agent Systems Builder – E-Commerce Automation", "Remote (Everywhere)", "https://wellfound.com/jobs/4867200-e-commerce-automation-operations-engineer-clone", "$80,000 - $120,000 Annually", "Python, LangChain, LangGraph, Multi-Agent Systems, Automation", "new", 3, "AI Agent / Agentic AI"),
        ("wellfound:4287738", "wellfound", "Metaworkers.ai", "Founding Engineer (Agentic AI)", "Remote (Global)", "https://wellfound.com/jobs/4287738-founding-engineer", "$50,000 - $80,000 Annually", "Agentic AI, Python, LLMs, LangGraph, Autonomous Workflows", "new", 3, "AI Agent / Agentic AI"),
        ("wellfound:4823718", "wellfound", "AssetIntel", "Backend Engineer (Remote - India)", "Remote (India)", "https://wellfound.com/jobs/4823718-senior-backend-engineer-remote-india", "₹25,000 - ₹45,000 / month", "Python, FastAPI, PostgreSQL, Docker, Microservices", "new", 2, "AI Engineer / Applied AI")
    ]

    for base_jid, src, comp, tit, loc, u, sal, skills, st, tier, cat in sample_target_jobs:
        # Check if this exact job URL has already been processed or applied
        existing = con.execute(
            "SELECT status FROM jobs WHERE url = ? AND status IN ('applied', 'already_applied', 'expired', 'rejected', 'ineligible', 'dropped_demographics_required')",
            (u,)
        ).fetchone()
        if existing:
            continue

        jid = f"{base_jid}:{today_slug}"
        con.execute("""
            INSERT INTO jobs (id, source, company, title, location, url, posted, kw_score, status, notes, target_tier, target_category)
            VALUES (?, ?, ?, ?, ?, ?, ?, 8, 'new', ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET 
                url = excluded.url,
                notes = excluded.notes,
                status = CASE WHEN status = 'failed' THEN 'new' ELSE status END
        """, (jid, src, comp, tit, loc, u, datetime.date.today().isoformat(), f"Salary: {sal} | Skills: {skills}", tier, cat))
    con.commit()
