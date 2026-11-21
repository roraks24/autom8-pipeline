import datetime
import json
import logging
from typing import Any, Dict, List

from job_discovery import fetch_internshala
from src.config import get_config_file
from src.core.classifier import classify_role, is_unpaid_role
from src.db.repository import get_connection

logger = logging.getLogger("internshala_discovery")


def discover_live_internshala_jobs(limit: int = 20) -> List[Dict[str, Any]]:
    """
    Fetches active Internshala listings across AI/GenAI/Agentic categories,
    filters them against candidate target tiers (Tiers 1-3 internships),
    and saves fresh jobs into jobs.db.
    """
    con = get_connection()
    today_str = datetime.date.today().isoformat()

    # Load slugs from boards.json
    boards_path = get_config_file("boards.json")
    slugs = [
        "work-from-home-artificial-intelligence-ai-internships",
        "work-from-home-machine-learning-internships",
        "work-from-home-python-development-internships",
        "work-from-home-python-django-internships",
        "work-from-home-backend-development-internships",
        "work-from-home-full-stack-development-internships",
        "work-from-home-software-development-internships",
        "work-from-home-web-development-internships",
        "work-from-home-data-science-internships",
    ]
    if boards_path.exists():
        try:
            b_data = json.loads(boards_path.read_text(encoding="utf-8"))
            slugs = b_data.get("internshala", slugs)
        except Exception:
            pass

    existing_urls = {row["url"] for row in con.execute("SELECT url FROM jobs WHERE source='internshala' AND status IN ('applied', 'already_applied', 'unpaid_excluded', 'ineligible', 'rejected', 'expired', 'dropped_demographics_required')").fetchall()}
    existing_ids = {row["id"] for row in con.execute("SELECT id FROM jobs WHERE source='internshala' AND status IN ('applied', 'already_applied', 'unpaid_excluded', 'ineligible', 'rejected', 'expired', 'dropped_demographics_required')").fetchall()}
    discovered = []

    for slug in slugs:
        if len(discovered) >= limit:
            break
        try:
            for job in fetch_internshala(slug):
                url = job.get("url", "")
                jid = f"internshala:{job['ext_id']}"
                if not url or url in existing_urls or jid in existing_ids:
                    continue

                desc = job.get("desc", "")
                # Candidate Policy: Strictly never discover, queue, or apply to unpaid roles
                if is_unpaid_role(text=desc, title=job.get("title", ""), salary=desc):
                    continue

                tier, cat, is_target = classify_role(
                    job["title"],
                    desc=desc,
                    url=url,
                    source="internshala"
                )

                if not is_target or tier not in (1, 2, 3):
                    continue

                notes = f"Salary: {job.get('desc', '')} | Skills: Python, AI, Problem Solving"

                con.execute("""
                    INSERT INTO jobs (id, source, company, title, location, url, posted, kw_score, status, notes, target_tier, target_category)
                    VALUES (?, 'internshala', ?, ?, ?, ?, ?, 8, 'new', ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        url = excluded.url,
                        notes = excluded.notes,
                        status = CASE WHEN status IN ('failed', 'staged_for_review') THEN 'new' ELSE status END
                """, (
                    jid,
                    job.get("company_name", "Company"),
                    job["title"],
                    job.get("location", "Work from home"),
                    url,
                    today_str,
                    notes,
                    tier,
                    cat
                ))
                existing_urls.add(url)
                existing_ids.add(jid)
                discovered.append(job)

                if len(discovered) >= limit:
                    break
        except Exception as e:
            logger.warning(f"Error fetching Internshala slug '{slug}': {e}")

    con.commit()
    print(f"  [Internshala Discovery] Added {len(discovered)} fresh target roles to jobs.db.")
    return discovered
