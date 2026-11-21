import json
import logging
import random
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from src.config import (
    ANSWER_BANK_PATH,
    BASE_DIR,
    DB_PATH,
    RESUMES_DIR,
    get_config_file,
    get_cookie_path,
    load_answer_bank,
)
from src.core.classifier import is_unpaid_role
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

        who_can_apply = soup.find(class_="who_can_apply")
        if who_can_apply:
            text = who_can_apply.get_text(" ", strip=True).lower()
            if "women only" in text or "only for women" in text or "exclusively for women" in text:
                res["reason"] = "Ineligible: Reserved exclusively for women candidates"
                return res

        # Candidate Policy: Never apply to unpaid internships
        stipend_el = soup.find(class_=lambda c: c and "stipend" in c)
        stipend_text = stipend_el.get_text(" ", strip=True) if stipend_el else ""
        full_page_text = soup.get_text(" ", strip=True)
        if is_unpaid_role(text=full_page_text, salary=stipend_text):
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
        jd_text: str = ""
    ) -> str:
        """Synthesizes high-impact answers tailored to candidate's verified profile and JD."""
        norm_label = label.lower().strip()
        personal = self.answers.get("personal", {})

        if field_type == "radio":
            return "Yes"

        if field_type == "range" or field_type == "select":
            if options:
                num_opts = [o for o in options if o.isdigit()]
                if num_opts:
                    return str(max([int(x) for x in num_opts]))
                return options[-1]
            return "5"

        if any(k in norm_label for k in ["availability", "join immediately", "start immediately", "duration"]):
            return "I am available to start immediately with 0 days notice, for a duration of 3 to 6 months, committing 40 hours/week full-time or 20-25 hours/week part-time."

        if any(k in norm_label for k in ["relocat", "in-office", "office", "delhi", "bangalore", "mumbai", "pune"]):
            return "Yes, I am open to relocate to Delhi/NCR, Bangalore, Mumbai, Pune or other locations for this internship."

        if any(k in norm_label for k in ["experience", "how many years", "years of experience"]):
            return "I have 1 year of hands-on experience building production GenAI applications (Rorak AI) and backend services with Python, FastAPI, and FAISS."

        if any(k in norm_label for k in ["pursuing", "which year", "degree", "college", "graduation", "current year"]):
            return "Currently in 2nd year pursuing B.Tech in Computer Science & Engineering (AI & ML) at JECRC University, graduating in 2029."

        if any(k in norm_label for k in ["stipend", "expected stipend", "salary", "compensation"]):
            return "₹25,000 - ₹35,000 / month (open to discussion as per company policy)."

        if any(k in norm_label for k in ["hours", "weekly", "per week"]):
            return "40 hours/week full-time or 20-25 hours/week part-time."

        if any(k in norm_label for k in ["portfolio", "github", "samples", "work sample", "link to your work", "past work"]):
            return (
                f"Live Portfolio: {personal.get('portfolio', 'https://www.rorak.tech')}\n"
                f"GitHub Profile: {personal.get('github', 'https://github.com/roraks24')}\n"
                f"LinkedIn: {personal.get('linkedin', 'https://www.linkedin.com/in/rorak/')}\n"
                "Featured production builds: Rorak AI (document-grounded RAG on FastAPI/Cloud Run) and "
                "FreelanceIQ (5-agent scoping architecture for NVIDIA Agentic AI Hackathon)."
            )

        if any(k in norm_label for k in ["built", "project", "interesting thing", "automation", "excel", "power bi"]):
            return (
                "I architected and shipped Rorak AI (live at https://www.rorak.tech), a production document-grounded "
                "RAG application containerized with Docker and deployed on Google Cloud Run. The backend is built with Python "
                "and FastAPI, utilizing FAISS vector indexing with cross-encoder reranking for semantic retrieval, and Groq's "
                "Llama 3.3 70B for low-latency responses. In addition, I designed a 5-agent collaborative scoping architecture "
                "for the NVIDIA + gnani.ai Agentic AI Hackathon with stateful cycle handling."
            )

        if any(k in norm_label for k in ["tools do you", "tools you use", "technologies", "tech stack", "software"]):
            return (
                "I regularly work with: 1) Cursor & VS Code with Claude 3.5 Sonnet / GPT-4o for code intelligence and rapid scaffolding, "
                "2) Groq API (Llama 3.3 70B) & OpenAI for low-latency inference and prompt engineering, "
                "3) LangGraph & LangSmith for multi-agent workflows, state management, and telemetry, and "
                "4) Python, FastAPI, Docker, and FAISS for scalable backend API development and vector search."
            )

        if any(k in norm_label for k in ["why should we hire", "why hire", "suitable", "fit for this role", "cover letter"]):
            std_pitch = self.answers.get("standard_answers", {}).get("why_hire_me")
            if std_pitch:
                return std_pitch
            skills_pitch = f" with strong skills in {', '.join(skills_required[:3])}" if skills_required else ""
            return (
                f"GenAI & Python Developer targeting {company_name or 'the team'}{skills_pitch}. "
                f"I have hands-on production experience building, containerizing, and deploying LLM applications and REST APIs. "
                f"Recently architected and shipped Rorak AI (FastAPI, FAISS, Google Cloud Run at www.rorak.tech), designed a 5-agent "
                f"scoping architecture for NVIDIA's Agentic AI Hackathon, and finalist in ISRO's BAH 2026. "
                f"I write clean, modular, tested Python code (pytest) with high autonomy and rapid turnaround in production environments."
            )

        if any(k in norm_label for k in ["design", "architecture", "overview", "system", "daily"]):
            return (
                "I would architect an automated data & AI pipeline: 1) Ingestion: Fetch POS sales, attendance, food inventory, "
                "and maintenance tickets into PostgreSQL/BigQuery via scheduled webhooks/cron jobs. 2) Analysis: A Python backend "
                "running scheduled agentic tasks computes KPIs and flags anomalies (e.g. food cost variance, ticket SLA breaches). "
                "3) Delivery: Auto-generate an executive 5-minute digest delivered via a streamlined web dashboard (FastAPI/Streamlit) "
                "and an automated daily WhatsApp/Telegram summary report."
            )

        return (
            f"Hands-on experience developing Python backends (FastAPI, Docker) and deploying production GenAI applications "
            f"(RAG pipelines with FAISS and multi-agent workflows in LangGraph). I write clean, robust code with rapid execution "
            f"and high autonomy for {company_name or 'the team'}."
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

        if not details["eligible"]:
            status_code = "unpaid_excluded" if "unpaid" in details.get("reason", "").lower() else "ineligible"
            result["status"] = status_code
            result["message"] = details["reason"]
            self._update_db_status(job_url, status_code, details["reason"])
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
                    self._update_db_status(job_url, "applied", f"Already Applied ({err_text})")
                elif "invalid job" in err_text.lower() or "closed" in err_text.lower():
                    result["status"] = "rejected"
                    self._update_db_status(job_url, "rejected", err_text)
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
                self._update_db_status(job_url, "dropped_demographics_required", result["message"])
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
                        jd_text=jd_text
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
                    opts = [o.get("value") for o in sel.find_all("option") if o.get("value")]
                    ans = self.synthesize_answer(
                        label_text,
                        "range",
                        options=opts,
                        job_title=details["job_title"],
                        company_name=details["company_name"],
                        skills_required=skills_req,
                        jd_text=jd_text
                    )
                    payload[sname] = ans
                    questions_answered.append({"question": label_text, "name": sname, "answer": ans})
                continue

            inp_text = group.find("input", {"type": lambda t: t in ["number", "text", None] or not t})
            if inp_text:
                iname = inp_text.get("name")
                if iname and iname not in ["confirm_availability", "confirm_availability_textarea"]:
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
                        ans = "30000"
                    elif any(k in norm_lbl for k in ["hours", "weekly hours", "per week"]):
                        ans = "40"
                    elif "github" in norm_lbl:
                        ans = "https://github.com/roraks24"
                    elif "portfolio" in norm_lbl or "website" in norm_lbl:
                        ans = "https://www.rorak.tech"
                    elif "linkedin" in norm_lbl:
                        ans = "https://www.linkedin.com/in/rorak/"
                    else:
                        ans = "1" if inp_text.get("type") == "number" or "numeric" in iname else "Yes"
                    payload[iname] = ans
                    questions_answered.append({"question": label_text, "name": iname, "answer": ans})
                continue

        result["questions_answered"] = questions_answered

        if mode == "stage":
            result["status"] = "staged_for_review"
            result["payload"] = payload
            result["message"] = f"Successfully staged application with {len(questions_answered)} answers prepared and tailored resume."
            self._update_db_status(job_url, "staged_for_review", json.dumps(payload))
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
                self._update_db_status(job_url, "applied", f"Application ID: {app_id}")
                logger.info(f"✅ Successfully applied to {details.get('company_name')} - ID: {app_id}")
                return result
            else:
                err = sub_data.get("errorThrown") or sub_data.get("errorCode") or "Submission rejected"
                result["status"] = "rejected"
                result["message"] = err
                self._update_db_status(job_url, "rejected", err)
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

    def _update_db_status(self, job_url: str, status: str, notes: str = ""):
        if not DB_PATH.exists():
            return
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            notes_str = json.dumps(notes) if isinstance(notes, (dict, list)) else str(notes)
            c.execute(
                "UPDATE jobs SET status = ?, notes = ? WHERE url = ?",
                (status, notes_str, job_url)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to update jobs.db: {e}")
