import datetime
import logging
import re
from typing import Any, Dict, List, Optional

from playwright.sync_api import sync_playwright

from src.config import ACTIVE_PLATFORMS, CHROME_PROFILE_DIR, load_boards_config
from src.core.browser import launch_persistent_context
from src.core.classifier import classify_role, is_excluded_company, is_unpaid_role, score_role_relevance
from src.storage.applied_store import AppliedJobsStore, SkippedCacheStore, is_known_job

logger = logging.getLogger("wellfound_discovery")

DEFAULT_WELLFOUND_ENDPOINTS = [
    "https://wellfound.com/jobs",
    "https://wellfound.com/role/l/ai-engineer/india",
    "https://wellfound.com/role/l/python-developer/india",
    "https://wellfound.com/role/l/full-stack-engineer/india",
    "https://wellfound.com/role/l/backend-engineer/india",
    "https://wellfound.com/role/l/software-engineer/india",
    "https://wellfound.com/role/l/frontend-engineer/india",
    "https://wellfound.com/role/l/react-developer/india",
    "https://wellfound.com/role/l/flutter-developer/india",
    "https://wellfound.com/role/l/ai-engineer/remote",
    "https://wellfound.com/role/l/python-developer/remote",
    "https://wellfound.com/role/l/full-stack-engineer/remote",
    "https://wellfound.com/role/l/backend-engineer/remote",
    "https://wellfound.com/location/india?page=2",
    "https://wellfound.com/location/india?page=3",
    "https://wellfound.com/location/india?page=4",
    "https://wellfound.com/location/india?page=5",
    "https://wellfound.com/location/india?page=6",
    "https://wellfound.com/location/india?page=7",
]

ALLOWED_GEO_TERMS = (
    "india", "bengaluru", "bangalore", "mumbai", "delhi", "pune", "hyderabad",
    "gurgaon", "noida", "jaipur", "chennai", "kolkata", "worldwide",
    "anywhere in the world", "global", "remote", "work from home",
)

FOREIGN_ONLY_TERMS = (
    "in-person in new york", "in-office in new york", "in-office in sf",
    "in-office in san francisco", "in-person in sf", "must reside in the united states",
    "must reside in the us", "must be based in us", "must be based in the us",
    "us only", "u.s. only", "usa only", "uk only", "canada only",
    "must reside in uk", "must reside in canada", "requires us citizenship",
    "us work authorization required", "us authorized",
    "must be authorized to work in the us", "no visa sponsorship",
    "sponsorship not available", "remote • united states", "remote only • united states",
    "remote • canada", "remote only • canada", "remote • united kingdom",
    "remote only • united kingdom",
)

EXTRACT_CARDS_JS = r"""() => {
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
}"""


def _normalize_endpoints() -> List[str]:
    cfg_wf = load_boards_config().get("wellfound", [])
    if not cfg_wf:
        return DEFAULT_WELLFOUND_ENDPOINTS
    urls: List[str] = []
    for entry in cfg_wf:
        if entry.startswith("http"):
            urls.append(entry)
        else:
            urls.append(f"https://wellfound.com/role/l/{entry.strip('/')}/india")
    return urls


def _passes_location_policy(card_lower: str, loc_lower: str) -> bool:
    has_allowed_geo = any(term in card_lower or term in loc_lower for term in ALLOWED_GEO_TERMS)
    if any(fc in card_lower or fc in loc_lower for fc in FOREIGN_ONLY_TERMS) and not has_allowed_geo:
        return False
    if (
        ("in office •" in card_lower or "in-office" in card_lower or "onsite only" in card_lower)
        and "jaipur" not in card_lower
        and "remote" not in card_lower
    ):
        return False
    return True


def discover_live_wellfound_jobs(
    limit: int = 20,
    applied_store: Optional[AppliedJobsStore] = None,
    skipped_store: Optional[SkippedCacheStore] = None,
    seen_urls: Optional[set] = None,
) -> List[Dict[str, Any]]:
    """
    Scans Wellfound multi-page directories via Playwright, enforces candidate
    compensation/location/tier filters, and returns fresh in-memory job targets.
    """
    applied_db = applied_store or AppliedJobsStore()
    skipped_db = skipped_store or SkippedCacheStore()
    endpoints = _normalize_endpoints()
    today_str = datetime.date.today().isoformat()
    local_seen = set(seen_urls or set())
    discovered_jobs: List[Dict[str, Any]] = []

    with sync_playwright() as p:
        context = launch_persistent_context(
            p,
            user_data_dir=CHROME_PROFILE_DIR,
            headless=True,
            load_cookies_for=ACTIVE_PLATFORMS,
        )
        page = context.pages[0] if context.pages else context.new_page()

        try:
            for url_endpoint in endpoints:
                if len(discovered_jobs) >= limit:
                    break

                print(f"  [Wellfound Discovery] Scanning: {url_endpoint}...", flush=True)
                try:
                    page.goto(url_endpoint, wait_until="commit", timeout=22000)
                    page.wait_for_timeout(3000)
                except Exception as ne:
                    print(f"  ! Timeout loading {url_endpoint}: {ne}", flush=True)
                    try:
                        page.close()
                    except Exception:
                        pass
                    page = context.new_page()
                    continue

                for _ in range(3):
                    page.evaluate("window.scrollBy(0, 1500)")
                    page.wait_for_timeout(500)
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(700)

                for item in page.evaluate(EXTRACT_CARDS_JS):
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

                    m = re.search(r"/jobs/(\d+)", url)
                    jid = f"wellfound:{m.group(1)}" if m else f"wellfound:{abs(hash(url))}"

                    if url in local_seen or jid in local_seen:
                        continue
                    local_seen.add(url)
                    local_seen.add(jid)

                    if is_excluded_company(comp):
                        continue

                    if is_unpaid_role(text=card, title=title, salary=sal):
                        skipped_db.record_skipped(
                            url=url, job_id=jid, source="wellfound", company=comp, title=title,
                            status="unpaid_excluded", reason="Unpaid/equity-only role excluded", flush=False
                        )
                        continue

                    if not _passes_location_policy(card_lower, loc_lower):
                        continue

                    known, _ = is_known_job(applied_db, skipped_db, url=url, job_id=jid, company=comp, title=title)
                    if known:
                        continue

                    tier, cat, is_tgt = classify_role(title, card, url=url, source="wellfound")
                    if not is_tgt or not tier:
                        continue

                    t_low = title.lower()
                    if any(k in t_low for k in ("data scientist", "computer vision", "nlp researcher", "deep learning researcher")):
                        continue

                    notes = f"Salary: {sal} | Skills: Python, FastAPI, GenAI, LLMs, Automation"
                    rel_score = score_role_relevance(title, card, comp)
                    discovered_jobs.append({
                        "id": jid,
                        "source": "wellfound",
                        "company": comp,
                        "title": title,
                        "location": loc,
                        "url": url,
                        "posted": today_str,
                        "salary": sal,
                        "skills": "Python, FastAPI, GenAI, LLMs, Automation",
                        "notes": notes,
                        "target_tier": tier,
                        "target_category": cat,
                        "relevance_score": rel_score,
                    })
        except Exception as e:
            logger.error(f"Wellfound discovery failed: {e}")
        finally:
            skipped_db.save()
            context.close()

    tier_order = {1: 1, 3: 2, 2: 3}
    discovered_jobs.sort(key=lambda j: (tier_order.get(j.get("target_tier", 2), 9), -j.get("relevance_score", 0)))
    print(f"  [Wellfound Discovery] Queued {len(discovered_jobs)} fresh target role(s).")
    return discovered_jobs
