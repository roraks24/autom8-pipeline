import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.appliers.ats import fill_ashby_form, fill_greenhouse_form, fill_lever_form
from src.core.llm import (
    align_expected_salary,
    answer_screening_question,
    generate_tailored_pitch,
)
from src.core.tailor import get_or_create_resume

REACT_SET_VALUE_JS = """([el, val]) => {
    if (!el || val === null || val === undefined) return false;
    el.focus();
    const proto = Object.getPrototypeOf(el);
    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
    if (desc && desc.set) {
        desc.set.call(el, String(val));
    } else {
        el.value = String(val);
    }
    if (el._valueTracker) el._valueTracker.setValue('');
    el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText' }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    el.dispatchEvent(new Event('blur', { bubbles: true }));
    return true;
}"""


def _extract_page_jd_and_salary(page) -> Dict[str, str]:
    """Extracts the full visible Wellfound JD text and salary header after page load."""
    try:
        return page.evaluate("""() => {
            const descEl = document.querySelector('[class*="styles_description"], [data-test="JobDetail-Description"], main');
            const jdText = (descEl ? descEl.innerText : document.body.innerText || '').trim().slice(0, 6000);
            const hdr = document.querySelector('h1')?.closest('div')?.parentElement || document.body;
            const hdrText = (hdr.innerText || '');
            const salMatch = hdrText.match(/[\\$₹][\\d,]+[kK]?(?:\\s*[–\\-]\\s*[\\$₹]?[\\d,]+[kK]?)?/);
            return { jdText, salary: salMatch ? salMatch[0] : '' };
        }""")
    except Exception:
        return {"jdText": "", "salary": ""}


def _resolve_react_select_dropdowns(page, company: str, job_title: str, jd_text: str, posted_salary: str) -> None:
    """Finds any unfilled React-Select dropdowns in the Wellfound modal and selects the best option."""
    try:
        controls = page.query_selector_all('[data-test="JobApplication-Modal"] [class*="select__control"], [role="dialog"] [class*="select__control"]')
        for ctrl in controls:
            try:
                has_val = ctrl.query_selector('[class*="singleValue"], [class*="multiValue"]')
                if has_val and has_val.inner_text().strip():
                    continue
                label_text = ctrl.evaluate("""el => {
                    let p = el.parentElement;
                    for (let i = 0; i < 4 && p; i++) {
                        const lbl = p.querySelector('label');
                        if (lbl && lbl.innerText.trim()) return lbl.innerText.trim();
                        p = p.parentElement;
                    }
                    return (el.parentElement?.parentElement?.innerText || '').split('\\n')[0].trim();
                }""")
                ctrl.click()
                page.wait_for_timeout(450)
                opts_els = page.query_selector_all('[class*="select__option"]')
                if not opts_els:
                    page.keyboard.press("Escape")
                    continue
                opts_texts = [o.inner_text().strip() for o in opts_els if o.inner_text().strip()]
                chosen_text = None
                if label_text and opts_texts:
                    chosen_text = answer_screening_question(
                        label_text,
                        field_type="select",
                        options=opts_texts,
                        company=company,
                        job_title=job_title,
                        jd_text=jd_text,
                        posted_salary=posted_salary,
                    )
                clicked = False
                if chosen_text:
                    for o in opts_els:
                        if o.inner_text().strip().lower() == chosen_text.strip().lower():
                            o.click()
                            clicked = True
                            break
                if not clicked and opts_els:
                    # Prefer Yes / India / Remote if available, else first option
                    preferred = next(
                        (o for o in opts_els if any(k in o.inner_text().lower() for k in ("yes", "india", "remote", "immediately", "relocate"))),
                        opts_els[0],
                    )
                    preferred.click()
                page.wait_for_timeout(400)
            except Exception:
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
    except Exception:
        pass


def _fill_dynamic_modal_questions(
    page,
    company: str,
    job_title: str,
    jd_text: str,
    posted_salary: str,
    portfolio_url: str,
    fallback_pitch: str,
) -> bool:
    """
    Fills all visible textareas and remaining empty text/number/select screening inputs
    using Groq JD-grounded synthesis + React 18 property setter.
    """
    filled_any = False
    try:
        modal = page.query_selector('[data-test="JobApplication-Modal"], [role="dialog"], .ReactModal__Content')
        if not modal:
            return False

        # 1. Standard HTML <select> elements inside modal
        for sel in modal.query_selector_all("select"):
            try:
                if sel.input_value():
                    continue
                opts = sel.evaluate("el => [...el.options].map(o => ({v: o.value, t: o.innerText.trim()})).filter(o => o.v)")
                if not opts:
                    continue
                lbl = sel.evaluate("el => el.closest('div')?.innerText?.split('\\n')[0] || ''")
                choice = answer_screening_question(
                    lbl or "Select option",
                    field_type="select",
                    options=[o["t"] for o in opts],
                    company=company,
                    job_title=job_title,
                    jd_text=jd_text,
                    posted_salary=posted_salary,
                )
                target_val = opts[0]["v"]
                if choice:
                    matched = next((o["v"] for o in opts if o["t"].lower() == choice.lower()), None)
                    if matched:
                        target_val = matched
                sel.select_option(target_val)
            except Exception:
                pass

        # 2. Checkboxes inside modal (terms / consent / acknowledgments)
        for cb in modal.query_selector_all('input[type="checkbox"]'):
            try:
                if not cb.is_checked():
                    cb.check(force=True)
            except Exception:
                pass

        # 3. Remaining empty text/number/url inputs missed by fast JS pass
        for inp in modal.query_selector_all('input[type="text"], input[type="number"], input:not([type])'):
            try:
                if not inp.is_visible() or (inp.input_value() or "").strip():
                    continue
                # Skip React-select's internal search box
                inp_cls = inp.get_attribute("class") or ""
                inp_id = inp.get_attribute("id") or ""
                if "select__input" in inp_cls or "react-select" in inp_id:
                    continue
                q_ctx = inp.evaluate("""el => {
                    const p = el.closest('div')?.parentElement || el.parentElement;
                    return (el.getAttribute('aria-label') || el.placeholder || (p ? p.innerText : '')).trim().slice(0, 240);
                }""")
                if not q_ctx:
                    continue
                is_num = (inp.get_attribute("type") == "number")
                ans = answer_screening_question(
                    q_ctx,
                    field_type="number" if is_num else "text",
                    company=company,
                    job_title=job_title,
                    jd_text=jd_text,
                    posted_salary=posted_salary,
                )
                if ans:
                    page.evaluate(REACT_SET_VALUE_JS, [inp, ans])
                    filled_any = True
            except Exception:
                pass

        # 4. All visible textareas (pitch note + custom screening textareas)
        textareas = modal.query_selector_all('textarea, [contenteditable="true"]')
        for idx, ta in enumerate(textareas):
            try:
                if not ta.is_visible():
                    continue
                q_label = ta.evaluate("""el => {
                    const id = el.id;
                    if (id) {
                        const l = document.querySelector(`label[for="${id}"]`);
                        if (l && l.innerText.trim()) return l.innerText.trim();
                    }
                    let parent = el.parentElement;
                    for (let i = 0; i < 3 && parent; i++) {
                        const lbl = parent.querySelector('label, h3, h4, p');
                        if (lbl && lbl.innerText.trim().length > 3) return lbl.innerText.trim();
                        parent = parent.parentElement;
                    }
                    return el.placeholder || '';
                }""")
                q_low = (q_label or "").lower()
                is_pitch = (
                    not q_low
                    or idx == 0
                    and any(k in q_low for k in ("note", "cover", "write a note", "why", "interest", "fit", "pitch", "message"))
                    or "write a note" in q_low
                )

                ans = None
                if is_pitch:
                    ans = generate_tailored_pitch(
                        company=company,
                        job_title=job_title,
                        jd_text=jd_text,
                    )
                else:
                    ans = answer_screening_question(
                        q_label,
                        field_type="textarea",
                        company=company,
                        job_title=job_title,
                        jd_text=jd_text,
                        posted_salary=posted_salary,
                    )

                final_text = ans or fallback_pitch
                if page.evaluate(REACT_SET_VALUE_JS, [ta, final_text]):
                    filled_any = True
            except Exception:
                pass

        if filled_any:
            print("  [Wellfound LLM] Filled custom pitch/screening fields via React Native Setter.")
    except Exception as e:
        print(f"  ! Dynamic modal filling warning: {e}")

    return filled_any


def fill_wellfound_form(
    page,
    answers: Dict[str, Any],
    resume_path: Optional[Path] = None,
    job_title: str = "GenAI Engineer",
    company: str = "Startup",
    submit: bool = False,
    salary: str = "",
    jd_text: str = "",
    out_meta: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Fills standardized Wellfound (AngelList) job application modal.
    Pipeline v2.0 Engine:
    - Extracts live JD & posted salary before compiling tailored ATS resume.
    - Waits for modal animation and GraphQL loading spinner resolution.
    - Aligns expected compensation dynamically to posted salary range.
    - Uses Groq LLM + Master Resume facts for company-specific pitch notes and custom screening questions.
    - Uses native property descriptor value setter & InputEvent to bypass React 18 state trapping.
    - Handles relocation radio, checkboxes, and React-select dropdowns cleanly.
    """
    personal = answers.get("personal", {})
    std_answers = answers.get("standard_answers", {})
    portfolio_url = personal.get("portfolio", "https://rohit-saini-dev.vercel.app")

    # 1. Dismiss common cookie/prompt banners
    for close_sel in ['button[aria-label="Close"]', 'button:has-text("Accept")', 'button:has-text("Dismiss")', 'button:has-text("Got it")']:
        btn = page.query_selector(close_sel)
        if btn:
            try:
                btn.click()
                page.wait_for_timeout(300)
            except Exception:
                pass

    current_url = page.url.lower()
    if "login" in current_url or "signup" in current_url:
        print("  [Notice] Wellfound requires authentication to apply.")
        return "login_required"

    login_btn = page.query_selector('header button:has-text("Log In"), header a:has-text("Log In"), button:has-text("Log In")')
    if login_btn and login_btn.is_visible():
        print("  [Notice] Wellfound account not logged in (Log In button detected).")
        return "login_required"

    # Check if job is expired or no longer available (including 404)
    is_closed = page.evaluate("""() => {
        const text = (document.body.innerText || '').toLowerCase();
        const title = (document.title || '').toLowerCase();
        return title.includes('404') ||
               text.includes('404: page not found') ||
               text.includes('the job listing is no longer available') ||
               text.includes('listing is no longer available') ||
               text.includes('this job is no longer available') ||
               text.includes('job expired') ||
               text.includes('job is closed');
    }""")
    if is_closed:
        print("  [Wellfound] Job listing is closed, expired, or returned 404.")
        return "expired"

    # Check if already applied
    is_already_applied = page.evaluate("""() => {
        const applyBtn = document.querySelector('[class*="styles_applyButton"]')
                      || [...document.querySelectorAll('button')].find(b => b.innerText.toLowerCase().includes('applied') && (b.innerText.toLowerCase().includes('✓') || b.disabled));
        if (applyBtn) {
            const t = (applyBtn.innerText || '').trim().toLowerCase();
            return t.includes('applied') && (t.includes('✓') || applyBtn.disabled || applyBtn.getAttribute('aria-disabled') === 'true');
        }
        return false;
    }""")
    if is_already_applied:
        print("  [Wellfound] Already applied to this job previously (✓ Applied detected).")
        return "already_applied"

    # 2. Check Candidate Eligibility (Compensation, Location, Visa)
    is_ineligible, inelig_reason = page.evaluate("""() => {
        const jobHeader = document.querySelector('h1')?.closest('div')?.parentElement || document.querySelector('h1')?.parentElement || document.body;
        const jobHeaderText = (jobHeader.innerText || '').toLowerCase();
        const isPaid = /[\\$₹]|(?:usd|inr|eur|gbp)\\b|\\b\\d+k\\b|\\b\\d+,\\d+\\b/.test(jobHeaderText) && !/\\b(?:0|zero)\\s*(?:stipend|salary|pay)/.test(jobHeaderText);

        if (!isPaid && (/\\bunpaid\\b|\\bno\\s*stipend\\b|\\b0\\s*stipend\\b|\\bzero\\s*stipend\\b|\\bvolunteer\\b|\\bpro\\s*bono\\b|\\bequity\\s*only\\b|\\bwithout\\s*pay\\b|\\bno\\s*salary\\b/.test(jobHeaderText))) {
            return [true, 'Unpaid or zero-compensation role excluded by candidate policy'];
        }
        const bodyText = (document.body.innerText || '').toLowerCase();
        if (bodyText.includes('not accepting applications from your current location')) {
            return [true, 'Employer not accepting applications from candidate location (India)'];
        }
        if (bodyText.includes('does not offer visa sponsorship') && bodyText.includes('your profile indicates you require sponsorship')) {
            return [true, 'Employer does not offer visa sponsorship'];
        }
        if (bodyText.includes('must reside in the united states') || bodyText.includes('must be located in the united states') || bodyText.includes('us work authorization required') || bodyText.includes('us citizen or green card')) {
            return [true, 'US residency / authorization required'];
        }
        if (bodyText.includes('must reside in the uk') || bodyText.includes('uk work authorization required')) {
            return [true, 'UK residency / authorization required'];
        }
        return [false, ''];
    }""")
    if is_ineligible:
        if "unpaid" in inelig_reason.lower() or "compensation" in inelig_reason.lower():
            print(f"  [Compensation Policy] {inelig_reason}. Marked unpaid_excluded.")
            return "unpaid_excluded"
        print(f"  [Eligibility Policy] {inelig_reason}. Marked ineligible.")
        return "ineligible"

    # Extract full live JD text & salary for real JD-based resume tailoring and LLM synthesis
    extracted = _extract_page_jd_and_salary(page)
    real_jd_text = extracted.get("jdText") or jd_text or ""
    real_salary = salary or extracted.get("salary") or ""
    if out_meta is not None:
        if real_salary:
            out_meta["salary"] = real_salary
        out_meta["jd_text"] = real_jd_text

    # Compile ATS tailored resume right here using the REAL scraped JD (if not pre-compiled)
    if resume_path is None:
        resume_path = get_or_create_resume(company=company, title=job_title, notes=real_jd_text)
        if out_meta is not None:
            out_meta["tailored_resume"] = str(resume_path)

    # 3. Locate and click 'Apply' button
    apply_clicked = page.evaluate("""() => {
        const btns = [...document.querySelectorAll('button, [class*="styles_applyButton"]')].filter(b => {
            const s = window.getComputedStyle(b);
            const t = b.innerText.trim().toLowerCase();
            return (t === 'apply' || t === 'apply now') && s.display !== 'none' && s.visibility !== 'hidden' && !b.disabled;
        });
        if (btns.length > 0) {
            btns[0].click();
            return true;
        }
        return false;
    }""")

    if not apply_clicked:
        apply_btn = page.query_selector('button[class*="styles_applyButton"], button[data-test="LearnMoreButton"], button:has-text("Apply Now"), button:has-text("Apply")')
        if apply_btn:
            try:
                apply_btn.click()
            except Exception:
                pass
        else:
            btn_applied = page.evaluate("""() => {
                const b = document.querySelector('[class*="styles_applyButton"]');
                return b && (b.disabled || b.innerText.toLowerCase().includes('applied'));
            }""")
            if btn_applied:
                return "already_applied"
            if "no longer available" in (page.inner_text("body") or "").lower():
                return "expired"

    # Wait for modal and past GraphQL spinner
    try:
        page.wait_for_selector('[data-test="JobApplication-Modal"], [role="dialog"], .ReactModal__Content', timeout=8000)
        for _ in range(10):
            has_fields = page.evaluate("""() => {
                const modal = document.querySelector('[data-test="JobApplication-Modal"], [role="dialog"], .ReactModal__Content');
                if (!modal) return false;
                return !!modal.querySelector('textarea, button[data-test="JobApplicationModal--SubmitButton"], input, button');
            }""")
            if has_fields:
                break
            page.wait_for_timeout(500)
    except Exception:
        btn_applied = page.evaluate("""() => {
            const b = document.querySelector('[class*="styles_applyButton"]');
            return b && (b.disabled || b.innerText.toLowerCase().includes('applied'));
        }""")
        if btn_applied:
            return "already_applied"
        if "no longer available" in (page.inner_text("body") or "").lower():
            return "expired"
        page.wait_for_timeout(2000)

    # Verify modal eligibility
    modal_inelig, modal_inelig_msg = page.evaluate("""() => {
        const modal = document.querySelector('[data-test="JobApplication-Modal"], [role="dialog"], .ReactModal__Content');
        if (!modal) return [false, ''];
        const text = (modal.innerText || '').toLowerCase();
        const modalIsPaid = /[\\$₹]|(?:usd|inr|eur|gbp)\\b|\\b\\d+k\\b|\\b\\d+,\\d+\\b/.test(text) && !/\\b(?:0|zero)\\s*(?:stipend|salary|pay)/.test(text);
        if (!modalIsPaid && (/\\bunpaid\\b|\\bno\\s*stipend\\b|\\b0\\s*stipend\\b|\\bzero\\s*stipend\\b|\\bvolunteer\\b|\\bpro\\s*bono\\b|\\bequity\\s*only\\b|\\bwithout\\s*pay\\b|\\bno\\s*salary\\b/.test(text))) {
            return [true, 'Unpaid or zero-compensation role excluded by candidate policy'];
        }
        if (text.includes('does not offer visa sponsorship') && text.includes('your profile indicates')) {
            return [true, 'Employer modal states no visa sponsorship offered for candidate profile'];
        }
        if (text.includes('not accepting applications from your current location')) {
            return [true, 'Employer not accepting applications from candidate location (India)'];
        }
        return [false, ''];
    }""")
    if modal_inelig:
        status_code = "unpaid_excluded" if "unpaid" in modal_inelig_msg.lower() or "compensation" in modal_inelig_msg.lower() else "ineligible"
        print(f"  [Policy Check] {modal_inelig_msg}. Closing modal and marking {status_code}.")
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return status_code

    if "login" in page.url.lower() or "signup" in page.url.lower():
        return "login_required"

    # External ATS redirects
    curr_url = page.url.lower()
    if "greenhouse.io" in curr_url:
        return fill_greenhouse_form(page, answers, resume_path)
    if "lever.co" in curr_url:
        return fill_lever_form(page, answers, resume_path)
    if "ashbyhq.com" in curr_url:
        return fill_ashby_form(page, answers, resume_path)

    # Demographics Blocker check
    has_demographics = page.evaluate("""() => {
        const modal = document.querySelector('[data-test="JobApplication-Modal"], [role="dialog"], .ReactModal__Content') || document.body;
        const text = modal.innerText || '';
        const patterns = [/\\bcgpa\\b/i, /\\bgpa\\b/i, /12th\\s*(percentage|percent|marks)/i, /10th\\s*(percentage|percent|marks)/i, /date\\s*of\\s*birth/i, /\\bdob\\b/i, /permanent\\s*address/i, /\\bpin\\s*code\\b/i];
        return patterns.some(p => p.test(text));
    }""")
    if has_demographics:
        print("  [Policy Drop] Modal mandates CGPA / 12th marks / DOB / Address. Dropping.")
        return "dropped_demographics_required"

    # 4. Handle Relocation Radio & Location Dropdowns
    try:
        reloc_label = page.query_selector('label[for*="relocate_to"], input[value="relocate_to"]')
        if reloc_label:
            reloc_label.click()
            page.wait_for_timeout(500)
        _resolve_react_select_dropdowns(page, company, job_title, real_jd_text, real_salary)
    except Exception:
        pass

    # 5. Fast-fill Standard Inputs & Screening Radio Groups (salary aligned to real_salary!)
    aligned_inr_num = align_expected_salary(real_salary, is_numeric=True, currency_hint="INR")
    aligned_usd_num = align_expected_salary(real_salary, is_numeric=True, currency_hint="USD")
    try:
        page.evaluate("""(userData) => {
            const modal = document.querySelector('[data-test="JobApplication-Modal"], [role="dialog"], .ReactModal__Content');
            if (!modal) return;

            const setVal = (el, val) => {
                if (!el || !val) return;
                el.focus();
                const desc = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value');
                if (desc && desc.set) desc.set.call(el, val);
                else el.value = val;
                if (el._valueTracker) el._valueTracker.setValue('');
                el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText' }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new Event('blur', { bubbles: true }));
            };

            const inputs = [...modal.querySelectorAll('input[type="text"], input[type="tel"], input[type="url"], input:not([type])')];
            for (const input of inputs) {
                if ((input.className || '').includes('select__input')) continue;
                if (input.value && input.value.trim().length > 0) continue;
                let labelText = '';
                if (input.id) {
                    const l = modal.querySelector(`label[for="${input.id}"]`);
                    if (l) labelText = l.innerText;
                }
                if (!labelText && input.closest('label')) labelText = input.closest('label').innerText;
                const name = (input.name || '').toLowerCase();
                const placeholder = (input.placeholder || '').toLowerCase();
                const containerText = input.closest('div')?.innerText || '';
                const fullCtx = (labelText + ' ' + name + ' ' + placeholder + ' ' + containerText).toLowerCase();

                if (fullCtx.includes('phone') || fullCtx.includes('mobile') || fullCtx.includes('contact')) {
                    setVal(input, userData.phone);
                } else if (fullCtx.includes('linkedin')) {
                    setVal(input, userData.linkedin);
                } else if (fullCtx.includes('github')) {
                    setVal(input, userData.github);
                } else if (fullCtx.includes('portfolio') || fullCtx.includes('website') || fullCtx.includes('url')) {
                    setVal(input, userData.portfolio);
                } else if (fullCtx.includes('experience') || fullCtx.includes('years')) {
                    setVal(input, "1");
                } else if (fullCtx.includes('salary') || fullCtx.includes('stipend') || fullCtx.includes('compensation') || fullCtx.includes('ctc')) {
                    setVal(input, (fullCtx.includes('$') || fullCtx.includes('usd')) ? userData.salaryUsd : userData.salaryInr);
                } else if (fullCtx.includes('notice') || fullCtx.includes('start date') || fullCtx.includes('earliest')) {
                    setVal(input, "Immediately");
                }
            }

            const allRadios = [...modal.querySelectorAll('input[type="radio"]')];
            const radioGroupsByName = {};
            for (const r of allRadios) {
                const name = r.name || ('unnamed_' + (r.id || Math.random()));
                if (!radioGroupsByName[name]) radioGroupsByName[name] = [];
                radioGroupsByName[name].push(r);
            }

            for (const name in radioGroupsByName) {
                const radios = radioGroupsByName[name];
                if (radios.some(r => r.checked)) continue;

                let container = radios[0].parentElement;
                while (container && container !== modal && container.querySelectorAll('input[type="radio"]').length <= radios.length) {
                    if (container.parentElement && container.parentElement.querySelectorAll('input[type="radio"]').length <= radios.length) {
                        container = container.parentElement;
                    } else {
                        break;
                    }
                }
                const grpText = (container ? container.innerText : '').toLowerCase();

                let targetRadio = null;
                if (grpText.includes('sponsorship') || grpText.includes('visa')) {
                    if (grpText.includes('in india') && !grpText.includes('outside india')) {
                        targetRadio = radios.find(r => (r.parentElement ? r.parentElement.innerText : '').toLowerCase().includes('no')) || radios[radios.length - 1];
                    } else {
                        targetRadio = radios.find(r => (r.parentElement ? r.parentElement.innerText : '').toLowerCase().includes('yes')) || radios[0];
                    }
                } else if (grpText.includes('authorized') || grpText.includes('legally')) {
                    if (grpText.includes('united states') || grpText.includes('u.s.') || grpText.includes('canada') || grpText.includes('uk') || grpText.includes('without sponsorship')) {
                        targetRadio = radios.find(r => (r.parentElement ? r.parentElement.innerText : '').toLowerCase().includes('no')) || radios[radios.length - 1];
                    } else {
                        targetRadio = radios.find(r => (r.parentElement ? r.parentElement.innerText : '').toLowerCase().includes('yes')) || radios[0];
                    }
                } else if (grpText.includes('relocat') || grpText.includes('office') || grpText.includes('location') || grpText.includes('miles') || grpText.includes('city')) {
                    targetRadio = radios.find(r => {
                        const t = (r.parentElement ? r.parentElement.innerText : '').toLowerCase();
                        return t.includes('relocate') || t.includes('yes') || t.includes('no, but willing');
                    }) || radios[0];
                } else {
                    targetRadio = radios.find(r => (r.parentElement ? r.parentElement.innerText : '').toLowerCase().includes('yes')) || radios[0];
                }

                if (targetRadio) {
                    targetRadio.checked = true;
                    targetRadio.dispatchEvent(new Event('input', { bubbles: true }));
                    targetRadio.dispatchEvent(new Event('change', { bubbles: true }));
                    if (targetRadio.parentElement) targetRadio.parentElement.click();
                    targetRadio.click();
                }
            }
        }""", {
            "phone": personal.get("phone", "+917877169982"),
            "linkedin": personal.get("linkedin", "https://www.linkedin.com/in/rorak/"),
            "github": personal.get("github", "https://github.com/roraks24"),
            "portfolio": portfolio_url,
            "salaryInr": aligned_inr_num,
            "salaryUsd": aligned_usd_num,
        })
        page.wait_for_timeout(400)
    except Exception as e:
        print(f"  ! Input fields filling warning: {e}")

    # 6. Dynamic JD-Grounded LLM Synthesis for Pitch + Custom Questions + Dropdowns + Checkboxes
    fallback_pitch = std_answers.get("why_hire_me") or (
        f"AI & Python Engineer applying for {job_title} at {company}. "
        f"I currently intern at Srishti GenAI working on Python/FastAPI backend architecture and built Rorak AI V2 "
        f"(document-grounded RAG with FAISS, cross-encoder reranking, Docker) and Agent Co (LangGraph multi-agent orchestration). "
        f"Available immediately; see {portfolio_url}."
    )
    _fill_dynamic_modal_questions(page, company, job_title, real_jd_text, real_salary, portfolio_url, fallback_pitch)
    _resolve_react_select_dropdowns(page, company, job_title, real_jd_text, real_salary)

    # 7. Upload ATS Tailored Resume
    file_input = page.query_selector('input[type="file"]')
    if file_input and resume_path and Path(resume_path).exists():
        try:
            file_input.set_input_files(str(resume_path))
            print(f"  [Upload] Attached tailored resume: {Path(resume_path).name}")
            page.wait_for_timeout(1000)
        except Exception as e:
            print(f"  ! File upload warning: {e}")

    # 8. Live Submission & Second-Screen Dismissal
    if submit:
        try:
            page.evaluate("""() => {
                const modal = document.querySelector('[data-test="JobApplication-Modal"], [role="dialog"], .ReactModal__Content');
                if (modal) modal.scrollTop = modal.scrollHeight;
            }""")
            page.wait_for_timeout(500)
        except Exception:
            pass

        send_btn = page.query_selector('button[data-test="JobApplicationModal--SubmitButton"], button:has-text("Send application"), button:has-text("Send Application")')
        if send_btn:
            is_disabled = send_btn.evaluate("el => el.disabled || el.getAttribute('aria-disabled') === 'true'")
            if is_disabled:
                # Retry React-selects / checkboxes once in case earlier interaction revealed dependent field
                _resolve_react_select_dropdowns(page, company, job_title, real_jd_text, real_salary)
                page.wait_for_timeout(800)
                is_disabled = send_btn.evaluate("el => el.disabled || el.getAttribute('aria-disabled') === 'true'")

            if not is_disabled:
                page.wait_for_timeout(int(1000 * (1.5 + (time.time() % 1.5))))
                print("  [Action] [Wellfound v2] Clicking 'Send application'...")
                send_btn.click()
                page.wait_for_timeout(3500)

                try:
                    dismiss_btn = page.query_selector('button[data-test="closeButton"], button[aria-label*="close" i], button:has-text("Done"), button:has-text("Skip"), button:has-text("Dismiss"), button:has-text("Not now")')
                    if dismiss_btn and dismiss_btn.is_visible():
                        print("  [Wellfound v2] Dismissing post-apply second screen...")
                        dismiss_btn.click()
                        page.wait_for_timeout(800)
                    else:
                        page.keyboard.press("Escape")
                except Exception:
                    pass

                print("  [Wellfound v2] ✅ Application successfully submitted!")
                return "applied"

            page_text = page.inner_text("body").lower()
            if "not accepting applications from your current location" in page_text or ("does not offer visa sponsorship" in page_text and "your profile indicates you require sponsorship" in page_text):
                print("  ! Ineligible: Employer location/visa constraint. Marked ineligible.")
                return "ineligible"
            print("  ! Submit button still disabled (unresolved custom field). Kept staged.")
            return "staged_for_review"

        btn_applied = page.evaluate("""() => {
            const b = document.querySelector('[class*="styles_applyButton"]');
            return b && (b.disabled || b.innerText.toLowerCase().includes('applied'));
        }""")
        if btn_applied:
            return "already_applied"
        if "no longer available" in (page.inner_text("body") or "").lower():
            return "expired"
        return "staged_for_review"

    return "staged_for_review"
