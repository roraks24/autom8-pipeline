import datetime
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

from playwright.sync_api import sync_playwright

from src.config import get_cookie_path
from src.core.classifier import classify_role, is_target_role, is_unpaid_role
from src.db.repository import get_connection

logger = logging.getLogger("wellfound_discovery")


def discover_live_wellfound_jobs(limit: int = 20) -> List[Dict[str, Any]]:
    """
    Connects to Wellfound with user cookies, scans multi-role directories
    (AI Engineer Remote/India, Backend India, Full-Stack India, Software Engineer, Internships),
    extracts active hiring roles, classifies them against candidate target tiers,
    and inserts fresh, verified jobs into jobs.db.
    """
    profile_dir = Path.home() / ".chrome_job_profile"
    cookie_path = get_cookie_path("wellfound")
    
    discovered_jobs = []
    today_str = datetime.date.today().isoformat()
    con = get_connection()
    
    discovery_endpoints = [
        ("https://wellfound.com/jobs", "Wellfound Main Feed"),
        ("https://wellfound.com/location/india?page=3", "India Startups Page 3"),
        ("https://wellfound.com/location/india?page=4", "India Startups Page 4"),
        ("https://wellfound.com/location/india?page=5", "India Startups Page 5"),
        ("https://wellfound.com/role/l/ai-engineer/india", "AI Engineer (India)"),
        ("https://wellfound.com/role/l/python-developer/india", "Python Developer (India)"),
        ("https://wellfound.com/role/l/full-stack-engineer/india", "Full-Stack Engineer (India)"),
        ("https://wellfound.com/role/l/backend-engineer/india", "Backend Engineer (India)"),
        ("https://wellfound.com/role/l/developer/india", "Developer (India)"),
        ("https://wellfound.com/role/l/internship/india", "Internship (India)"),
        ("https://wellfound.com/role/l/software-engineer/india", "Software Engineer (India)"),
        ("https://wellfound.com/role/l/web-developer/india", "Web Developer (India)"),
        ("https://wellfound.com/role/l/full-stack-engineer/india?page=2", "FullStack India Page 2"),
        ("https://wellfound.com/role/l/backend-engineer/india?page=2", "Backend India Page 2"),
        ("https://wellfound.com/role/l/software-engineer/india?page=2", "SWE India Page 2"),
        ("https://wellfound.com/role/l/internship/india?page=2", "Internship India Page 2"),
        ("https://wellfound.com/role/l/full-stack-engineer/india?page=3", "FullStack India Page 3"),
        ("https://wellfound.com/role/l/backend-engineer/india?page=3", "Backend India Page 3"),
        ("https://wellfound.com/role/l/ai-engineer/remote", "AI Engineer (Remote)"),
        ("https://wellfound.com/role/l/python-developer/remote", "Python Developer (Remote)"),
        ("https://wellfound.com/role/l/full-stack-engineer/remote", "Full-Stack Engineer (Remote)"),
        ("https://wellfound.com/role/l/backend-engineer/remote", "Backend Engineer (Remote)"),
        ("https://wellfound.com/role/l/software-engineer/remote", "Software Engineer (Remote)"),
        ("https://wellfound.com/location/bengaluru", "Bengaluru Startups"),
        ("https://wellfound.com/location/gurugram", "Gurugram Startups"),
        ("https://wellfound.com/location/noida", "Noida Startups"),
        ("https://wellfound.com/location/delhi", "Delhi Startups"),
        ("https://wellfound.com/location/hyderabad", "Hyderabad Startups"),
        ("https://wellfound.com/location/pune", "Pune Startups"),
        ("https://wellfound.com/location/mumbai", "Mumbai Startups"),
        ("https://wellfound.com/location/india?page=2", "India Startups Page 2"),
    ]
    
    with sync_playwright() as p:
        try:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=True,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 900}
            )
        except Exception:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=True,
                viewport={"width": 1280, "height": 900}
            )

        if cookie_path.exists():
            try:
                with open(cookie_path, "r", encoding="utf-8") as f:
                    context.add_cookies(json.load(f))
            except Exception:
                pass

        page = context.pages[0] if context.pages else context.new_page()
        
        try:
            for url_endpoint, label in discovery_endpoints:
                if len(discovered_jobs) >= limit:
                    break
                    
                print(f"  [Wellfound Discovery] Scanning directory: {label} ({url_endpoint})...", flush=True)
                try:
                    page.goto(url_endpoint, wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_timeout(2000)
                except Exception as ne:
                    print(f"  ! Timeout loading {label}, skipping to next: {ne}", flush=True)
                    try:
                        page.close()
                    except Exception:
                        pass
                    page = context.new_page()
                    continue

                # Scroll down to load multiple job listings
                for _ in range(3):
                    page.evaluate("window.scrollBy(0, 1500)")
                    page.wait_for_timeout(600)
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(800)

                # Attempt to click any visible "View more" button
                try:
                    for btn in page.query_selector_all('button:has-text("View more"), button:has-text("Load more")'):
                        if btn.is_visible():
                            btn.click()
                            page.wait_for_timeout(2000)
                except Exception:
                    pass

                # Extract job cards
                raw_listings = page.evaluate(r"""() => {
                    const results = [];
                    const links = [...document.querySelectorAll('a[href*="/jobs/"]')];
                    for (const a of links) {
                        const href = a.getAttribute('href') || a.href || '';
                        if (!href.includes('/jobs/') || href.includes('/jobs/collections') || href.includes('/jobs/location')) continue;
                        
                        const m = href.match(/\/jobs\/(\d+)/);
                        if (!m) continue;

                        const title = a.innerText.split('\n')[0].trim();
                        if (!title || title.length < 3) continue;

                        let company = 'Startup';
                        let salary = 'Competitive / Market Standard';
                        let location = 'Remote / India';

                        // Walk up to find company name and container
                        let parent = a.parentElement;
                        let cardContainer = parent;
                        while (parent && parent !== document.body) {
                            const compLink = parent.querySelector('a[href*="/company/"]');
                            if (compLink && compLink.innerText.trim()) {
                                company = compLink.innerText.trim().split('\n')[0];
                                cardContainer = parent;
                                break;
                            }
                            const h2 = parent.querySelector('h2, h3, [class*="company"]');
                            if (h2 && h2.innerText.trim()) {
                                company = h2.innerText.trim().split('\n')[0];
                                cardContainer = parent;
                                break;
                            }
                            parent = parent.parentElement;
                        }

                        const cardText = (cardContainer ? cardContainer.innerText : a.innerText).trim();
                        if (cardText.includes('$') || cardText.includes('₹')) {
                            const sm = cardText.match(/[\$₹][\d,]+[kK]?\s*([–\-]\s*[\$₹]?[\d,]+[kK]?)?/);
                            if (sm) salary = sm[0];
                        }

                        const fullUrl = href.startsWith('http') ? href : 'https://wellfound.com' + href;
                        if (!results.some(r => r.url === fullUrl)) {
                            results.push({
                                title: title,
                                company: company,
                                url: fullUrl,
                                salary: salary,
                                location: location,
                                cardText: cardText
                            });
                        }
                    }
                    return results;
                }""")

                for item in raw_listings:
                    if len(discovered_jobs) >= limit:
                        break

                    title = item["title"]
                    comp = item["company"]
                    url = item["url"]
                    sal = item["salary"]
                    loc = item["location"]
                    card = item["cardText"]
                    card_lower = card.lower()
                    loc_lower = loc.lower()

                    # Strict Candidate Policy: Never apply to unpaid / volunteer / equity-only roles
                    if is_unpaid_role(text=card, title=title, salary=sal):
                        continue

                    # Strict Candidate Eligibility Filter (Candidate is based in Jaipur, India)
                    has_india_or_global = any(ic in card_lower or ic in loc_lower for ic in [
                        "india", "bengaluru", "bangalore", "mumbai", "delhi", "pune", "hyderabad",
                        "gurgaon", "noida", "jaipur", "chennai", "kolkata", "worldwide", "anywhere in the world", "global"
                    ])
                    # Skip listings that demand foreign presence or specific foreign authorization
                    if any(fc in card_lower or fc in loc_lower for fc in [
                        "in-person in new york", "in-office in new york", "in-office in sf", "in-office in san francisco",
                        "in-person in sf", "must reside in the united states", "must reside in the us", "must be based in us",
                        "must be based in the us", "us only", "u.s. only", "usa only", "uk only", "canada only",
                        "must reside in uk", "must reside in canada", "requires us citizenship", "us work authorization required",
                        "us authorized", "must be authorized to work in the us", "no visa sponsorship", "sponsorship not available",
                        "remote • united states", "remote only • united states", "remote • canada", "remote only • canada",
                        "remote • united kingdom", "remote only • united kingdom"
                    ]) and not has_india_or_global:
                        continue

                    # Skip non-Jaipur in-office roles without remote option
                    if ("in office •" in card_lower or "in-office" in card_lower or "onsite only" in card_lower) and "jaipur" not in card_lower and "remote" not in card_lower:
                        continue

                    # Exclude if candidate already applied, ineligible, expired, or excluded by policy
                    existing = con.execute(
                        "SELECT status FROM jobs WHERE (url = ? OR (lower(company) = ? AND lower(title) = ?)) AND status IN ('applied', 'already_applied', 'unpaid_excluded', 'ineligible', 'expired', 'non_target_role', 'rejected')",
                        (url, comp.lower().strip(), title.lower().strip())
                    ).fetchone()
                    if existing:
                        continue

                    # Extract numeric job ID
                    m = re.search(r"/jobs/(\d+)", url)
                    jid = f"wellfound:{m.group(1)}" if m else f"wellfound:{abs(hash(url))}"

                    # Classify role
                    tier, cat, is_tgt = classify_role(title, card, url=url, source="wellfound")
                    if not is_tgt or not tier:
                        continue

                    # Exclude pure Machine Learning Engineer / Data Science roles (Candidate Policy)
                    if any(k in title.lower() for k in ["data scientist", "computer vision", "nlp researcher", "deep learning researcher"]):
                        continue

                    # Exclude senior/staff roles
                    if any(re.search(r"\b" + s + r"\b", title.lower()) for s in ["senior", "sr", "lead", "manager", "head", "director", "principal", "staff"]):
                        continue

                    notes = f"Salary: {sal} | Skills: Python, FastAPI, GenAI, LLMs, Automation"
                    
                    # Insert or update in jobs.db as fresh 'new' job (never overwrite already resolved terminal statuses)
                    con.execute("""
                        INSERT INTO jobs (id, source, company, title, location, url, posted, kw_score, status, notes, target_tier, target_category)
                        VALUES (?, 'wellfound', ?, ?, ?, ?, ?, 8, 'new', ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            url = excluded.url,
                            title = excluded.title,
                            notes = excluded.notes,
                            posted = excluded.posted,
                            target_tier = excluded.target_tier,
                            target_category = excluded.target_category,
                            status = CASE WHEN status IN ('failed', 'staged_for_review') THEN 'new' ELSE status END
                    """, (jid, comp, title, loc, url, today_str, notes, tier, cat))
                    
                    if not any(dj["id"] == jid for dj in discovered_jobs):
                        discovered_jobs.append({
                            "id": jid,
                            "source": "wellfound",
                            "company": comp,
                            "title": title,
                            "tier": tier,
                            "target_tier": tier,
                            "category": cat,
                            "target_category": cat,
                            "url": url,
                            "salary": sal,
                            "notes": notes,
                            "status": "new"
                        })

                con.commit()

            print(f"  [Wellfound Discovery] Successfully discovered and queued {len(discovered_jobs)} fresh Target Roles (Tiers 1-3) into jobs.db.")

        except Exception as e:
            logger.error(f"  ! Wellfound discovery failed: {e}")
        finally:
            context.close()

    return discovered_jobs


if __name__ == "__main__":
    jobs = discover_live_wellfound_jobs()
    for j in jobs:
        print(f"• [Tier {j['tier']}: {j['category']}] {j['company']} - {j['title']} -> {j['url']}")
