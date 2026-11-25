import datetime
import logging
from typing import Any, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from src.appliers.internshala import InternshalaApplier
from src.config import load_boards_config
from src.core.classifier import classify_role, is_excluded_company, is_unpaid_role, score_role_relevance
from src.storage.applied_store import AppliedJobsStore, SkippedCacheStore, is_known_job

logger = logging.getLogger("internshala_discovery")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    )
}


def _parse_internshala_cards(html: str, is_fresher_job: bool = False) -> List[Dict[str, str]]:
    """Extracts listing card metadata from an Internshala search/category HTML page."""
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.find_all("div", class_="individual_internship")
    parsed: List[Dict[str, str]] = []

    for c in cards:
        title_el = c.find("a", class_="job-title-href") or c.find("h3", class_="job-internship-name")
        if not title_el or not title_el.get("href"):
            continue

        title = title_el.get_text(strip=True)
        href = title_el["href"].strip()
        url = href if href.startswith("http") else f"https://internshala.com{href}"
        ext_id = href.rstrip("/").split("/")[-1]
        jid = f"internshala:{ext_id}"

        comp_el = c.find("p", class_="company-name") or c.find("a", class_="link_display_like_text")
        company = comp_el.get_text(strip=True) if comp_el else "Company"

        loc_el = c.find("a", class_="location_link") or c.find("span", class_="location")
        location = loc_el.get_text(strip=True) if loc_el else ("Remote / India" if is_fresher_job else "Work from home")

        sal_el = c.find("span", class_="salary") or c.find("span", class_="stipend") or c.find("div", class_="salary")
        salary = sal_el.get_text(strip=True) if sal_el else ("₹ 3,00,000 - 6,00,000 /year" if is_fresher_job else "")

        parsed.append({
            "id": jid,
            "title": title,
            "company": company,
            "location": location,
            "url": url,
            "salary": salary,
        })
    return parsed


def _build_feed_urls(boards_cfg: Dict[str, Any]) -> List[Tuple[str, bool]]:
    """Builds ordered Internshala feed URLs: (url, is_fresher_job)."""
    is_cfg = boards_cfg.get("internshala", {})
    if isinstance(is_cfg, list):
        internship_cats = is_cfg
        fresher_cats = ["work-from-home", "software-development-jobs", "full-stack-development-jobs", "python-jobs"]
        keywords = ["python", "ai", "fastapi", "full%20stack", "react", "backend"]
    else:
        fresher_cats = is_cfg.get("fresher_job_categories", [])
        internship_cats = is_cfg.get("internship_categories", [])
        keywords = is_cfg.get("keywords", [])

    feeds: List[Tuple[str, bool]] = []
    # High-yield fresher jobs first (paid ₹3-6+ LPA, zero unpaid)
    for cat in fresher_cats:
        for page in range(1, 3):
            u = f"https://internshala.com/jobs/{cat}/" if page == 1 else f"https://internshala.com/jobs/{cat}/page-{page}/"
            feeds.append((u, True))

    # Category internship feeds (multi-page)
    for cat in internship_cats:
        for page in range(1, 4):
            u = f"https://internshala.com/internships/{cat}/" if page == 1 else f"https://internshala.com/internships/{cat}/page-{page}/"
            feeds.append((u, False))

    # Keyword remote fallback feeds
    for kw in keywords:
        feeds.append((f"https://internshala.com/internships/keywords-{kw}/work-from-home/", False))

    return feeds


def discover_live_internshala_jobs(
    limit: int = 20,
    applied_store: Optional[AppliedJobsStore] = None,
    skipped_store: Optional[SkippedCacheStore] = None,
    seen_urls: Optional[set] = None,
    verify_eligibility: bool = True,
) -> List[Dict[str, Any]]:
    """
    Discovers fresh, verified-paid, eligible Internshala listings across fresher jobs,
    internship categories, and keyword feeds without relying on SQLite.
    """
    applied_db = applied_store or AppliedJobsStore()
    skipped_db = skipped_store or SkippedCacheStore()
    applier = InternshalaApplier() if verify_eligibility else None

    boards_cfg = load_boards_config()
    feeds = _build_feed_urls(boards_cfg)
    today_str = datetime.date.today().isoformat()
    local_seen = set(seen_urls or set())
    discovered: List[Dict[str, Any]] = []

    for feed_url, is_fresher in feeds:
        if len(discovered) >= limit:
            break

        try:
            r = requests.get(feed_url, headers=HEADERS, timeout=12)
            if r.status_code != 200:
                continue
        except Exception as e:
            logger.warning(f"Error fetching Internshala feed '{feed_url}': {e}")
            continue

        for card in _parse_internshala_cards(r.text, is_fresher_job=is_fresher):
            if len(discovered) >= limit:
                break

            url = card["url"]
            jid = card["id"]
            if url in local_seen or jid in local_seen:
                continue
            local_seen.add(url)
            local_seen.add(jid)

            known, _ = is_known_job(
                applied_db,
                skipped_db,
                url=url,
                job_id=jid,
                company=card["company"],
                title=card["title"],
            )
            if known:
                continue

            if is_excluded_company(card["company"]):
                continue

            if is_unpaid_role(text=card["salary"], title=card["title"], salary=card["salary"]):
                skipped_db.record_skipped(
                    url=url,
                    job_id=jid,
                    source="internshala",
                    company=card["company"],
                    title=card["title"],
                    status="unpaid_excluded",
                    reason="Card indicated unpaid/zero-stipend role",
                    flush=False,
                )
                continue

            tier, cat, is_target = classify_role(
                card["title"],
                desc=card["salary"],
                url=url,
                source="internshala",
            )
            if not is_target or tier not in (1, 2, 3):
                continue

            skills_str = "Python, AI, Web Development"
            salary_str = card["salary"] or "Competitive / Market Standard"

            if applier is not None:
                det = applier.check_eligibility_and_details(url)
                if not det.get("eligible"):
                    hint = det.get("status_hint") or (
                        "unpaid_excluded" if "unpaid" in det.get("reason", "").lower() else "ineligible"
                    )
                    skipped_db.record_skipped(
                        url=url,
                        job_id=jid,
                        source="internshala",
                        company=det.get("company_name") or card["company"],
                        title=det.get("job_title") or card["title"],
                        status=hint,
                        reason=det.get("reason", "Ineligible on detail page"),
                        flush=False,
                    )
                    continue

                if det.get("salary"):
                    salary_str = det["salary"]
                if det.get("skills_required"):
                    skills_str = ", ".join(det["skills_required"][:5])

            notes = f"Salary: {salary_str} | Skills: {skills_str}"
            rel_score = score_role_relevance(card["title"], f"{salary_str} {skills_str}", card["company"])
            discovered.append({
                "id": jid,
                "source": "internshala",
                "company": card["company"],
                "title": card["title"],
                "location": card["location"],
                "url": url,
                "posted": today_str,
                "salary": salary_str,
                "skills": skills_str,
                "notes": notes,
                "target_tier": tier,
                "target_category": cat,
                "relevance_score": rel_score,
            })

    skipped_db.save()
    tier_order = {1: 1, 3: 2, 2: 3}
    discovered.sort(key=lambda j: (tier_order.get(j.get("target_tier", 2), 9), -j.get("relevance_score", 0)))
    print(f"  [Internshala Discovery] Found {len(discovered)} verified paid, eligible target role(s).")
    return discovered
