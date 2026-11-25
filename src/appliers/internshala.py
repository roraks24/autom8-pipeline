import json
import logging
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from src.config import (
    GITHUB_URL,
    LINKEDIN_URL,
    PORTFOLIO_URL,
    RESUMES_DIR,
    get_config_file,
    get_cookie_path,
    load_answer_bank,
)
from src.core.classifier import is_unpaid_role
from src.core.llm import (
    align_expected_salary,
    answer_screening_question,
    generate_tailored_pitch,
)
from src.core.tailor import generate_pdf, tailor_resume_data

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("internshala_applier")


def fill_internshala_form(page, answers: Dict[str, Any], resume_path: Path) -> str:
    """Fills Internshala application form modal via Playwright DOM interaction."""
    # Close any promo/signup popups or subscription alerts
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    try:
        page.evaluate('''() => {
            document.querySelectorAll(".subscription_alert, .modal-backdrop, #subscription_modal").forEach(el => el.remove());
            document.body.classList.remove("modal-open");
        }''')
    except Exception:
        pass

    for sel in ['button.close', '.modal-close', 'i.ic-24-cross', 'div.close-icon', 'button:has-text("Later")']:
        el = page.query_selector(sel)
        if el:
            try:
                el.click()
                page.wait_for_timeout(300)
            except Exception:
                pass

    # Click Apply now
    apply_btn = page.query_selector('button#easy_apply_button, button:has-text("Apply now"), a:has-text("Apply now")')
    if apply_btn:
        try:
            apply_btn.click(force=True)
            page.wait_for_timeout(2500)
        except Exception:
            pass

    content = page.content()
    if "registration/student" in page.url or "login" in page.url.lower() or "Sign up to apply" in content:
        print("  [Notice] Internshala login required to apply.")
        return "login_required"

    # Fill 'Why should you be hired for this role?'
    for ta in page.query_selector_all('textarea'):
        if not ta.input_value():
            ta.fill(answers.get("standard_answers", {}).get("why_hire_me", ""))

    # Availability radio button
    avail_radio = page.query_selector('input[type="radio"][value*="yes"], label:has-text("Yes, I am available")')
    if avail_radio:
        try:
            avail_radio.click()
        except Exception:
            pass

    return "staged_for_review"


class InternshalaApplier:
    def __init__(self, cookies_file: Optional[Path] = None, answer_bank_file: Optional[Path] = None):
        self.cookies_file = Path(cookies_file) if cookies_file else get_cookie_path("internshala")
        self.answer_bank_file = Path(answer_bank_file) if answer_bank_file else get_config_file("answer_bank.json")
        self.answers = self._load_answer_bank()
        self.session = requests.Session()
        self._init_session()

    def _load_answer_bank(self) -> Dict[str, Any]:
        return load_answer_bank()

    def _init_session(self):
        if not self.cookies_file.exists():
            raise FileNotFoundError(f"Internshala cookies file not found at {self.cookies_file}")

        with open(self.cookies_file, "r", encoding="utf-8") as f:
            raw_cookies = json.load(f)

        cookie_dict = {}
        if isinstance(raw_cookies, list):
            for c in raw_cookies:
                cookie_dict[c["name"]] = c["value"]
        elif isinstance(raw_cookies, dict):
            cookie_dict = raw_cookies

        self.session.cookies.update(cookie_dict)
        self.csrf_token = cookie_dict.get("csrf_cookie_name", "")

        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 OPR/114.0.0.0",
            "Referer": "https://internshala.com/student/applications/",
            "Origin": "https://internshala.com",
            "X-Requested-With": "XMLHttpRequest",
            "X-Frontend-Request": "1",
            "X-Auth-Token-Is": "1"
        })

    def verify_session(self) -> Tuple[bool, Optional[str]]:
        """Verifies if the current session is valid and candidate is logged in."""
        try:
            r = self.session.post("https://internshala.com/api/candidate/dashboard/paginated_applications/new/1", timeout=10)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
                data = r.json()
                if data.get("success"):
                    return True, "Session verified active"
            return False, f"Unexpected response: status {r.status_code}"
        except Exception as e:
            return False, str(e)

    def check_eligibility_and_details(self, job_url: str) -> Dict[str, Any]:
        """Fetches job detail page, checks candidate eligibility, and extracts IDs."""
        res = {
            "eligible": False,
            "internship_id": None,
            "job_url_slug": None,
            "company_name": "",
            "job_title": "",
            "reason": ""
        }

        r = self.session.get(job_url, timeout=12)
        if r.status_code != 200:
            res["reason"] = f"Job page returned HTTP {r.status_code}"
            return res

        html = r.text
        match = re.search(r"var\s+internship_id\s*=\s*(\d+);", html)
        if match:
            res["internship_id"] = int(match.group(1))
        else:
            res["reason"] = "Could not locate internship_id in page JavaScript"
            return res

        slug = job_url.rstrip("/").split("/")[-1]
        res["job_url_slug"] = slug

        soup = BeautifulSoup(html, "html.parser")

        title_el = soup.find(class_="profile")
        if title_el:
            res["job_title"] = title_el.get_text(strip=True)
        comp_el = soup.find(class_="company_name")
        if comp_el:
            res["company_name"] = comp_el.get_text(strip=True)

        raw_skills = [el.get_text(strip=True) for el in soup.find_all(class_="round_tabs")]
        perk_words = ["certificate", "letter of recommendation", "flexible", "5 days", "informal", "free snacks"]
        tech_skills = [s for s in raw_skills if not any(p in s.lower() for p in perk_words)]
        res["skills_required"] = tech_skills

        jd_sections = []
        for el in soup.find_all(class_=lambda c: c and ("text-container" in c or "internship_details" in c)):
            t = el.get_text(" ", strip=True)
            if t and len(t) > 20:
                jd_sections.append(t)
        res["jd_text"] = " ".join(jd_sections)

        full_page_text = soup.get_text(" ", strip=True)

        who_can_apply = soup.find(class_="who_can_apply")
        if who_can_apply:
            text = who_can_apply.get_text(" ", strip=True).lower()
            if "women only" in text or "only for women" in text or "exclusively for women" in text:
                res["reason"] = "Ineligible: Reserved exclusively for women candidates"
                return res

        # Check button state and explicit ineligibility (location/relocation/profile mismatch)
        btn = soup.find(class_=lambda c: c and "apply_now_btn" in c)
        if btn:
            btn_text = btn.get_text(" ", strip=True).lower()
            is_disabled = btn.has_attr("disabled") or "disabled" in (btn.get("class") or [])
            if "already applied" in btn_text:
                res["status_hint"] = "already_applied"
                res["reason"] = "Already applied on Internshala"
                return res
            if "not eligible" in btn_text or is_disabled:
                res["status_hint"] = "ineligible"
                res["reason"] = f"Ineligible: Internshala button state: {btn.get_text(strip=True)}"
                return res
        if "you are not eligible" in full_page_text.lower():
            res["status_hint"] = "ineligible"
            res["reason"] = "Ineligible: Location or profile requirement mismatch flagged by Internshala"
            return res

        # Candidate Policy: Never apply to unpaid internships
        stipend_el = (
            soup.find("span", class_="stipend")
            or soup.find(class_=lambda c: c and "stipend" in c)
            or soup.find(class_=lambda c: c and "salary" in c)
        )
        raw_stipend = stipend_el.get_text(" ", strip=True) if stipend_el else ""
        clean_sal = re.search(
            r"(?:₹|\$|rs\.?|inr)\s*[\d,]+(?:\s*[–\-]\s*(?:₹|\$)?\s*[\d,]+)?(?:\s*/\s*(?:month|year|mo|yr|week|annum))?",
            raw_stipend,
            re.I,
        )
        stipend_text = clean_sal.group(0).strip() if clean_sal else raw_stipend
        res["salary"] = stipend_text
        if is_unpaid_role(text=full_page_text, salary=stipend_text):
            res["status_hint"] = "unpaid_excluded"
            res["reason"] = "Ineligible: Unpaid role excluded by candidate policy"
            return res

        res["eligible"] = True
        return res

    def synthesize_answer(
        self,
        label: str,
        field_type: str,
        options: Optional[List[str]] = None,
        job_title: str = "",
        company_name: str = "",
        skills_required: Optional[List[str]] = None,
        jd_text: str = "",
        posted_salary: str = "",
        option_value_map: Optional[Dict[str, str]] = None,
    ) -> str:
        """Synthesizes JD-grounded answers tailored to candidate's verified Master Resume."""
        norm_label = label.lower().strip()
        personal = self.answers.get("personal", {})
        portfolio = personal.get("portfolio", PORTFOLIO_URL)
        github = personal.get("github", GITHUB_URL)
        linkedin = personal.get("linkedin", LINKEDIN_URL)

        if field_type == "radio":
            return "Yes"

        if field_type in ("range", "select"):
            if options:
                llm_choice = answer_screening_question(
                    label,
                    field_type="select",
                    options=options,
                    company=company_name,
                    job_title=job_title,
                    jd_text=jd_text,
                    posted_salary=posted_salary,
                    skills_required=skills_required,
                )
                if llm_choice:
                    return option_value_map.get(llm_choice, llm_choice) if option_value_map else llm_choice
                num_opts = [o for o in options if o.isdigit()]
                if num_opts:
                    if "year" in norm_label or "experience" in norm_label:
                        chosen = "1" if "1" in num_opts else num_opts[0]
                    else:
                        chosen = str(max(int(x) for x in num_opts))
                    return option_value_map.get(chosen, chosen) if option_value_map else chosen
                chosen = options[0]
                return option_value_map.get(chosen, chosen) if option_value_map else chosen
            return "5"

        if any(k in norm_label for k in ["availability", "join immediately", "start immediately", "duration"]):
            return "I am available to start immediately (0 days notice) for 3 to 6 months, committing 40 hours/week full-time or 20-25 hours/week part-time."

        if any(k in norm_label for k in ["relocat", "in-office", "office", "delhi", "bangalore", "mumbai", "pune", "jaipur", "hyderabad"]):
            return "Yes, I am based in Jaipur and open to relocate or work in-office across major tech hubs as required."

        if any(k in norm_label for k in ["pursuing", "which year", "degree", "college", "graduation", "current year"]):
            return "Currently in 2nd year pursuing B.Tech in Computer Science & Engineering (AI & ML) at JECRC University, graduating in 2029."

        if any(k in norm_label for k in ["stipend", "expected stipend", "salary", "compensation"]):
            return align_expected_salary(posted_salary, currency_hint=label)

        if any(k in norm_label for k in ["hours", "weekly", "per week"]):
            return "40 hours/week full-time or 20-25 hours/week part-time."

        if any(k in norm_label for k in ["portfolio", "github", "samples", "work sample", "link to your work", "past work"]):
            return (
                f"Live Portfolio: {portfolio}\n"
                f"GitHub Profile: {github}\n"
                f"LinkedIn: {linkedin}\n"
                "Featured builds: Rorak AI V2 (FastAPI RAG with FAISS cross-encoder reranking) and "
                "Agent Co (FastAPI + LangGraph autonomous execution engine)."
            )

        # Why should we hire you / Cover letter -> Grounded JD-specific 3-sentence pitch
        if any(k in norm_label for k in ["why should we hire", "why hire", "suitable", "fit for this role", "cover letter"]):
            llm_pitch = generate_tailored_pitch(
                company=company_name or "the company",
                job_title=job_title or "Engineer",
                jd_text=jd_text,
                skills_required=skills_required,
            )
            if llm_pitch:
                return llm_pitch
            skills_pitch = f" with hands-on skills in {', '.join(skills_required[:4])}" if skills_required else ""
            return (
                f"AI & Python Engineer applying for {job_title or 'this role'} at {company_name or 'your team'}{skills_pitch}. "
                f"I currently intern at Srishti GenAI working on Python/FastAPI AI architecture and built Rorak AI V2 "
                f"(document-grounded RAG with FAISS reranking, PostgreSQL, Docker) and Agent Co (LangGraph multi-agent orchestration). "
                f"I am available immediately and share my work at {portfolio} and {github}."
            )

        # Any other open-ended technical / project / experience question -> Grounded Groq synthesis
        llm_ans = answer_screening_question(
            label,
            field_type=field_type if field_type in ("text", "number") else "textarea",
            company=company_name,
            job_title=job_title,
            jd_text=jd_text,
            posted_salary=posted_salary,
            skills_required=skills_required,
        )
        if llm_ans:
            return llm_ans

        return (
            f"I have hands-on internship and project experience building Python/FastAPI backends, "
            f"FAISS RAG pipelines (Rorak AI V2), and multi-agent workflows (Agent Co with LangGraph). "
            f"My portfolio is live at {portfolio} and code at {github}."
        )

    def apply_to_job(self, job_url: str, mode: str = "submit") -> Dict[str, Any]:
        result = {
            "url": job_url,
            "status": "failed",
            "mode": mode,
            "company": "",
            "title": "",
            "application_id": None,
            "message": "",
            "tailored_resume": None
        }

        # 1. Eligibility Check & JD Extraction
        details = self.check_eligibility_and_details(job_url)
        result["company"] = details.get("company_name", "")
        result["title"] = details.get("job_title", "")
        result["salary"] = details.get("salary", "")
        result["skills_required"] = details.get("skills_required", [])

        if not details["eligible"]:
            hint = details.get("status_hint")
            if hint:
                status_code = hint
            else:
                status_code = "unpaid_excluded" if "unpaid" in details.get("reason", "").lower() else "ineligible"
            result["status"] = status_code
            result["message"] = details["reason"]
            return result

        internship_id = details["internship_id"]
        slug = details["job_url_slug"]
        skills_req = details.get("skills_required", [])
        jd_text = details.get("jd_text", "")

        # 2. Review JD & Generate Tailored ATS Resume
        clean_comp = re.sub(r"[^a-zA-Z0-9_-]", "_", details.get("company_name", "Company"))
        clean_title = re.sub(r"[^a-zA-Z0-9_-]", "_", details.get("job_title", "Role"))[:30]
        tailored_pdf_path = RESUMES_DIR / f"Rohit_Saini_{clean_comp}_{clean_title}.pdf"

        logger.info(f"📋 [JD Review] Reviewing role: {details['company_name']} - {details['job_title']}")
        if skills_req:
            logger.info(f"   Skills Identified: {', '.join(skills_req)}")

        ctx = tailor_resume_data(
            target_title=details["job_title"],
            target_company=details["company_name"],
            jd_text=jd_text,
            skills_required=skills_req
        )
        generate_pdf(ctx, tailored_pdf_path)
        result["tailored_resume"] = str(tailored_pdf_path)
        logger.info(f"   [ATS Resume] Tailored PDF generated: {tailored_pdf_path.name}")

        # 3. Fetch Easy Apply Modal
        try:
            r_easy = self.session.post(
                "https://internshala.com/application/easy_apply",
                data={"internship_id": internship_id},
                timeout=12
            )
            if r_easy.status_code != 200:
                result["message"] = f"easy_apply endpoint returned HTTP {r_easy.status_code}"
                return result

            easy_data = r_easy.json()
            if not easy_data.get("success"):
                err_text = str(easy_data.get("errorThrown", "Unknown error"))
                result["message"] = f"easy_apply failed: {err_text}"
                if "already applied" in err_text.lower():
                    result["status"] = "already_applied"
                elif "invalid job" in err_text.lower() or "closed" in err_text.lower():
                    result["status"] = "rejected"
                return result
        except Exception as e:
            result["message"] = f"easy_apply request error: {str(e)}"
            return result

        modal_html = easy_data.get("application_modal_view", "")
        soup = BeautifulSoup(modal_html, "html.parser")
        form = soup.find("form")
        if not form:
            result["message"] = "Could not find application form in easy_apply response"
            return result

        # 4. Assemble Form Payload
        payload = {}
        for inp in form.find_all("input"):
            name = inp.get("name")
            itype = inp.get("type", "").lower()
            val = inp.get("value", "")
            if not name:
                continue
            if itype == "radio" or itype == "file":
                continue
            payload[name] = val

        payload["confirm_availability"] = "yes"
        payload["confirm_availability_textarea"] = ""

        questions_answered = []
        for group in soup.find_all(class_=lambda c: c and "form-group" in c):
            label_el = group.find("label")
            label_text = label_el.get_text(strip=True) if label_el else ""
            norm_lbl = label_text.lower()

            # Strict policy: Drop internships that mandate CGPA, 12th percentage, DOB, or permanent address
            if any(k in norm_lbl for k in ["cgpa", "gpa", "12th percentage", "12th marks", "10th marks", "board percentage", "date of birth", "dob", "birth date", "permanent address", "pin code", "postal code", "aadhaar", "pan card"]):
                logger.info(f"   [Policy Drop] Form requires mandatory academic/demographic screening: '{label_text}'. Dropping internship.")
                result["status"] = "dropped_demographics_required"
                result["message"] = f"Dropped: Requires mandatory CGPA / 12th marks / DOB / Address ({label_text})"
                return result

            txt = group.find("textarea")
            if txt:
                tname = txt.get("name")
                if tname and tname not in ["confirm_availability_textarea"]:
                    ans = self.synthesize_answer(
                        label_text,
                        "textarea",
                        job_title=details["job_title"],
                        company_name=details["company_name"],
                        skills_required=skills_req,
                        jd_text=jd_text,
                        posted_salary=details.get("salary", ""),
                    )
                    payload[tname] = ans
                    questions_answered.append({"question": label_text, "name": tname, "answer": ans})
                continue

            radios = group.find_all("input", {"type": "radio"})
            if radios:
                rname = radios[0].get("name")
                if rname and rname not in ["confirm_availability"]:
                    pos_val = "Yes"
                    for r in radios:
                        if "yes" in r.get("value", "").lower() or "yes" in (r.find_parent().get_text() if r.find_parent() else "").lower():
                            pos_val = r.get("value")
                            break
                    payload[rname] = pos_val
                    questions_answered.append({"question": label_text, "name": rname, "answer": pos_val})
                continue

            sel = group.find("select")
            if sel:
                sname = sel.get("name")
                if sname:
                    opt_map: Dict[str, str] = {}
                    opt_labels: List[str] = []
                    for o in sel.find_all("option"):
                        val_attr = (o.get("value") or "").strip()
                        lbl_attr = o.get_text(" ", strip=True) or val_attr
                        if val_attr and lbl_attr.lower() not in ("select", "choose", "--select--"):
                            opt_labels.append(lbl_attr)
                            opt_map[lbl_attr] = val_attr
                    ans = self.synthesize_answer(
                        label_text,
                        "range",
                        options=opt_labels,
                        job_title=details["job_title"],
                        company_name=details["company_name"],
                        skills_required=skills_req,
                        jd_text=jd_text,
                        posted_salary=details.get("salary", ""),
                        option_value_map=opt_map,
                    )
                    payload[sname] = ans
                    questions_answered.append({"question": label_text, "name": sname, "answer": ans})
                continue

            inp_text = group.find("input", {"type": lambda t: t in ["number", "text", None] or not t})
            if inp_text:
                iname = inp_text.get("name")
                if iname and iname not in ["confirm_availability", "confirm_availability_textarea"]:
                    is_num = inp_text.get("type") == "number" or "numeric" in iname
                    if any(k in norm_lbl for k in ["year", "experience", "how many years"]):
                        ans = "1"
                    elif any(k in norm_lbl for k in ["which year", "college year", "current year", "pursuing"]):
                        ans = "2"
                    elif any(k in norm_lbl for k in ["scale", "rating", "rate", "out of 5"]):
                        ans = "5"
                    elif any(k in norm_lbl for k in ["out of 10"]):
                        ans = "10"
                    elif any(k in norm_lbl for k in ["month", "duration"]):
                        ans = "6"
                    elif any(k in norm_lbl for k in ["notice", "days"]):
                        ans = "0"
                    elif any(k in norm_lbl for k in ["stipend", "compensation", "salary", "inr"]):
                        ans = align_expected_salary(
                            details.get("salary", ""),
                            is_numeric=is_num,
                            currency_hint=label_text,
                        )
                    elif any(k in norm_lbl for k in ["hours", "weekly hours", "per week"]):
                        ans = "40"
                    elif "github" in norm_lbl:
                        ans = self.answers.get("personal", {}).get("github", GITHUB_URL)
                    elif "portfolio" in norm_lbl or "website" in norm_lbl:
                        ans = self.answers.get("personal", {}).get("portfolio", PORTFOLIO_URL)
                    elif "linkedin" in norm_lbl:
                        ans = self.answers.get("personal", {}).get("linkedin", LINKEDIN_URL)
                    else:
                        llm_val = answer_screening_question(
                            label_text,
                            field_type="number" if is_num else "text",
                            company=details["company_name"],
                            job_title=details["job_title"],
                            jd_text=jd_text,
                            posted_salary=details.get("salary", ""),
                            skills_required=skills_req,
                        )
                        ans = llm_val or ("1" if is_num else "Yes")
                    payload[iname] = ans
                    questions_answered.append({"question": label_text, "name": iname, "answer": ans})
                continue

        result["questions_answered"] = questions_answered

        if mode == "stage":
            result["status"] = "staged_for_review"
            result["payload"] = payload
            result["message"] = f"Successfully staged application with {len(questions_answered)} answers prepared and tailored resume."
            return result

        submit_url = f"https://internshala.com/application/submit/{slug}"
        logger.info(f"Submitting live application to {submit_url}...")

        # Natural reading/review pause before final submission
        review_pause = round(random.uniform(2.0, 4.5), 1)
        time.sleep(review_pause)

        files = None
        file_obj = None
        if tailored_pdf_path.exists():
            file_obj = open(tailored_pdf_path, "rb")
            files = {"custom_resume": (tailored_pdf_path.name, file_obj, "application/pdf")}

        try:
            r_sub = None
            for sub_attempt in range(2):
                try:
                    if files and file_obj:
                        file_obj.seek(0)
                    r_sub = self.session.post(submit_url, data=payload, files=files, timeout=35)
                    break
                except requests.exceptions.RequestException as e:
                    if sub_attempt == 0:
                        logger.warning(f"Submit attempt 1 timed out ({e}). Retrying in 2 seconds...")
                        time.sleep(2)
                    else:
                        raise e

            if r_sub.status_code != 200:
                result["message"] = f"Submit returned HTTP {r_sub.status_code}: {r_sub.text[:200]}"
                return result

            sub_data = r_sub.json()
            if sub_data.get("success") or "applicationId" in sub_data:
                app_id = sub_data.get("applicationId")
                result["status"] = "applied"
                result["application_id"] = app_id
                result["message"] = f"Application successfully submitted! Application ID: {app_id}"
                logger.info(f"✅ Successfully applied to {details.get('company_name')} - ID: {app_id}")
                return result
            else:
                err = sub_data.get("errorThrown") or sub_data.get("errorCode") or "Submission rejected"
                result["status"] = "rejected"
                result["message"] = err
                return result
        except Exception as e:
            result["message"] = f"Exception during application submit: {str(e)}"
            return result
        finally:
            if file_obj:
                try:
                    file_obj.close()
                except Exception:
                    pass

    def get_recent_applications(self, limit: int = 10) -> List[Dict[str, Any]]:
        try:
            r = self.session.post("https://internshala.com/api/candidate/dashboard/paginated_applications/new/1", timeout=10)
            if r.status_code == 200:
                data = r.json()
                return data.get("applications", [])[:limit]
            return []
        except Exception as e:
            logger.error(f"Error fetching recent applications: {e}")
            return []

    def fetch_dashboard_applications(self, max_pages: int = 5) -> Dict[str, Any]:
        """Fetches paginated Internshala dashboard application statuses."""
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://internshala.com/student/applications",
        }
        applications: List[Dict[str, Any]] = []
        pages_fetched = 0
        total_pages_available = 1

        for page in range(1, max(1, max_pages) + 1):
            url = f"https://internshala.com/api/candidate/dashboard/paginated_applications/new/{page}"
            try:
                r = self.session.post(url, headers=headers, data={}, timeout=15)
                if r.status_code != 200:
                    logger.warning(f"Dashboard sync page {page} returned HTTP {r.status_code}")
                    break
                data = r.json()
                if not data.get("success", True):
                    break
                pages_fetched += 1
                total_pages_available = int(data.get("total_pages") or pages_fetched)
                batch = data.get("applications", []) or []
                if not batch:
                    break
                applications.extend(batch)
                if page >= total_pages_available:
                    break
            except Exception as e:
                logger.error(f"Error fetching dashboard page {page}: {e}")
                break

        return {
            "applications": applications,
            "pages_fetched": pages_fetched,
            "total_pages_available": total_pages_available,
        }

    def sync_application_outcomes(self, applied_store: Any, max_pages: int = 5) -> Dict[str, Any]:
        """Syncs Internshala dashboard statuses back into data/applied_jobs.json."""
        fetched = self.fetch_dashboard_applications(max_pages=max_pages)
        apps = fetched["applications"]
        status_counts: Dict[str, int] = {}
        positive_leads: List[Dict[str, Any]] = []
        updated = 0

        for item in apps:
            status = (item.get("application_status") or "").strip() or "Applied"
            status_counts[status] = status_counts.get(status, 0) + 1
            has_assignment = bool(item.get("assignment_link"))
            has_interview = bool(item.get("interview_link"))

            if status.lower() not in ("applied", "seen", "not selected", "rejected", "expired", "withdrawn") or has_assignment or has_interview:
                positive_leads.append({
                    "id": item.get("id"),
                    "company": item.get("company_name"),
                    "title": item.get("profile_to_display"),
                    "status": status,
                    "applied_at": item.get("applied_at"),
                    "url": item.get("url"),
                    "interview_link": item.get("interview_link"),
                    "assignment_link": item.get("assignment_link"),
                })

            changed = applied_store.update_outcome(
                application_id=str(item.get("id")) if item.get("id") else None,
                url=item.get("url") or "",
                outcome=status,
                company=item.get("company_name") or "",
                title=item.get("profile_to_display") or "",
                source="internshala",
                vha_score=item.get("vha_score"),
                has_assignment=has_assignment,
                has_interview=has_interview,
                flush=False,
            )
            if changed:
                updated += 1

        if updated > 0:
            applied_store.save_batch()

        return {
            "pages_fetched": fetched["pages_fetched"],
            "total_pages_available": fetched["total_pages_available"],
            "apps_scanned": len(apps),
            "updated": updated,
            "status_counts": status_counts,
            "positive_leads": positive_leads,
        }


def sync_internshala_outcomes(max_pages: int = 5) -> Dict[str, Any]:
    """Convenience helper to sync Internshala application outcomes into data/applied_jobs.json."""
    from src.storage.applied_store import AppliedJobsStore

    store = AppliedJobsStore()
    applier = InternshalaApplier()
    res = applier.sync_application_outcomes(store, max_pages=max_pages)
    res["db_outcome_counts"] = store.get_stats().get("outcome_counts", {})
    return res
