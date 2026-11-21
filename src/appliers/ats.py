import re
import time
from pathlib import Path
from typing import Any, Dict, Optional


def check_demographics_blocker(page) -> bool:
    """
    Detects if the application form mandates CGPA, 12th percentage, Date of Birth, 
    or permanent address / strict KYC verification.
    Returns True if demographic blockers are found.
    """
    try:
        return page.evaluate("""() => {
            const labels = [...document.querySelectorAll('label, div[class*="field"], div[class*="question"], p, span')];
            const patterns = [
                /\\bcgpa\\b/i,
                /\\bgpa\\b/i,
                /12th\\s*(percentage|percent|marks|board)/i,
                /10th\\s*(percentage|percent|marks|board)/i,
                /date\\s*of\\s*birth/i,
                /\\bdob\\b/i,
                /permanent\\s*address/i,
                /residential\\s*address/i,
                /\\bpin\\s*code\\b/i,
                /\\bpostal\\s*code\\b/i,
                /\\baadhaar\\b/i,
                /\\bpan\\s*(card|number)\\b/i
            ];
            for (const el of labels) {
                const text = el.innerText || '';
                if (text.length > 120) continue; // Skip long disclaimers
                for (const pat of patterns) {
                    if (pat.test(text)) {
                        const hasInput = el.querySelector('input, select, textarea') || 
                                         (el.htmlFor && document.getElementById(el.htmlFor)) ||
                                         el.closest('div')?.querySelector('input, select, textarea');
                        if (hasInput) return true;
                    }
                }
            }
            return false;
        }""")
    except Exception:
        return False


def fill_ashby_form(page, answers: Dict[str, Any], resume_path: Path) -> Optional[str]:
    """Fills standardized Ashby application forms."""
    if check_demographics_blocker(page):
        print("  [Policy Drop] Ashby form mandates CGPA / 12th percentage / DOB / Address. Dropping internship.")
        return "dropped_demographics_required"

    personal = answers.get("personal", {})
    name_parts = personal.get("full_name", "").split(" ", 1)
    first_name = name_parts[0]
    last_name = name_parts[1] if len(name_parts) > 1 else ""
    std_answers = answers.get("standard_answers", {})

    # Click Apply button or Application tab if present
    for sel in ['a:has-text("Application")', '[role="tab"]:has-text("Application")', 'button:has-text("Application")', 'button:has-text("Apply")', 'a:has-text("Apply for this Job")']:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                page.wait_for_timeout(2500)
                break
        except Exception:
            pass

    # Re-check blocker after tab click
    if check_demographics_blocker(page):
        print("  [Policy Drop] Ashby form mandates CGPA / 12th percentage / DOB / Address. Dropping internship.")
        return "dropped_demographics_required"

    # 1. Upload Resume
    file_inputs = page.query_selector_all('input[type="file"]')
    for fi in file_inputs:
        try:
            fi.set_input_files(str(resume_path))
        except Exception:
            pass
    if file_inputs:
        print(f"  [Upload] Attached tailored resume: {resume_path.name}")
        page.wait_for_timeout(3500)

    # 2. Fill Name
    name_loc = page.locator('input[name="_systemfield_name"]')
    if name_loc.count() > 0:
        name_loc.click()
        name_loc.fill(personal.get("full_name", ""))
    else:
        fn = page.locator('input[name*="first_name"], input[placeholder*="First Name"]')
        if fn.count() > 0: fn.fill(first_name)
        ln = page.locator('input[name*="last_name"], input[placeholder*="Last Name"]')
        if ln.count() > 0: ln.fill(last_name)

    # 3. Fill Email
    email_loc = page.locator('input[name="_systemfield_email"], input[type="email"]')
    if email_loc.count() > 0:
        email_loc.click()
        email_loc.fill(personal.get("email", ""))

    # 4. Fill Phone
    phone_loc = page.locator('input[type="tel"], input[name="_systemfield_phone"]')
    if phone_loc.count() > 0:
        phone_loc.click()
        phone_loc.fill(personal.get("phone", ""))

    # 5. Fill Location
    loc_input = page.query_selector('input[placeholder*="Start typing"], div:has-text("currently located") input, input[name*="location"]')
    if loc_input and not loc_input.input_value():
        try:
            loc_input.fill("India")
            page.wait_for_timeout(600)
            page.keyboard.press("ArrowDown")
            page.keyboard.press("Enter")
        except Exception:
            pass

    # 6. Fill Notice Period / Earliest Start Date
    date_input = page.query_selector('input[placeholder*="Pick date"], div:has-text("start a new role") input, input[placeholder*="Notice period"]')
    if date_input and not date_input.input_value():
        try:
            date_input.fill("Immediately (0 days notice)")
        except Exception:
            pass

    # 7. Answer Yes/No Radios
    for div in page.query_selector_all('div:has(> label), div[class*="question"], [role="radiogroup"], fieldset'):
        text = div.inner_text().lower()
        if any(k in text for k in ["sponsorship", "visa sponsor", "require sponsor", "require visa", "visa status", "h-1b", "work visa", "work permit"]):
            if "in india" in text and "outside india" not in text:
                no_btn = div.query_selector('button:has-text("No"), label:has-text("No"), [role="radio"]:has-text("No"), input[value*="no" i]')
                if no_btn:
                    try: no_btn.click()
                    except Exception: pass
            else:
                # User directive: If asked whether working visa / sponsorship is required for country other than India, say YES!
                yes_btn = div.query_selector('button:has-text("Yes"), label:has-text("Yes"), [role="radio"]:has-text("Yes"), input[value*="yes" i]')
                if yes_btn:
                    try: yes_btn.click()
                    except Exception: pass
        elif any(k in text for k in ["authorized to work", "legally authorized", "eligible to work", "right to work"]):
            if any(c in text for c in ["united states", "u.s.", "canada", "uk", "united kingdom", "without sponsorship", "without visa"]):
                no_btn = div.query_selector('button:has-text("No"), label:has-text("No"), [role="radio"]:has-text("No"), input[value*="no" i]')
                if no_btn:
                    try: no_btn.click()
                    except Exception: pass
            else:
                yes_btn = div.query_selector('button:has-text("Yes"), label:has-text("Yes"), [role="radio"]:has-text("Yes"), input[value*="yes" i]')
                if yes_btn:
                    try: yes_btn.click()
                    except Exception: pass
        elif "over 18" in text or "18 years" in text:
            yes_btn = div.query_selector('button:has-text("Yes"), label:has-text("Yes"), [role="radio"]:has-text("Yes"), input[value*="yes" i]')
            if yes_btn:
                try: yes_btn.click()
                except Exception: pass
        elif "relocat" in text or "open to relocate" in text:
            yes_btn = div.query_selector('button:has-text("Yes"), label:has-text("Yes")')
            if yes_btn:
                try: yes_btn.click()
                except Exception: pass
        elif "remote" in text and ("comfortable" in text or "experience" in text or "willing" in text):
            yes_btn = div.query_selector('button:has-text("Yes"), label:has-text("Yes")')
            if yes_btn:
                try: yes_btn.click()
                except Exception: pass

    # 8. Checkboxes
    for cb in page.query_selector_all('input[type="checkbox"]'):
        try:
            if not cb.is_checked():
                cb.check(force=True)
        except Exception:
            pass

    # 9. Links & Custom Questions
    all_inputs = page.query_selector_all('input[type="text"], input:not([type]), textarea')
    for inp in all_inputs:
        ph = (inp.get_attribute("placeholder") or "").lower()
        name = (inp.get_attribute("name") or "").lower()
        combined = f"{ph} {name}"
        if not inp.input_value():
            if "linkedin" in combined:
                inp.fill(personal.get("linkedin", ""))
            elif "github" in combined:
                inp.fill(personal.get("github", ""))
            elif "website" in combined or "portfolio" in combined:
                inp.fill(personal.get("portfolio", ""))
            elif any(k in combined for k in ["experience", "years of"]):
                inp.fill("1")
            elif any(k in combined for k in ["salary", "compensation", "stipend", "desired"]):
                inp.fill("$2,000 / month")
            elif any(k in combined for k in ["notice", "earliest", "start date"]):
                inp.fill("Immediately (0 days notice)")
            elif any(k in combined for k in ["hours", "weekly"]):
                inp.fill("40 hours/week")
            elif any(k in combined for k in ["why", "cover", "pitch", "note"]):
                inp.fill(std_answers.get("why_hire_me", ""))

    return None


def fill_lever_form(page, answers: Dict[str, Any], resume_path: Path) -> Optional[str]:
    """Fills standardized Lever application forms."""
    if check_demographics_blocker(page):
        print("  [Policy Drop] Lever form mandates CGPA / 12th percentage / DOB / Address. Dropping internship.")
        return "dropped_demographics_required"

    personal = answers.get("personal", {})
    std_answers = answers.get("standard_answers", {})

    apply_btn = page.query_selector('a.postings-btn[href*="apply"], a:has-text("Apply for this job")')
    if apply_btn:
        try:
            apply_btn.click()
            page.wait_for_timeout(2000)
        except Exception:
            pass

    if check_demographics_blocker(page):
        print("  [Policy Drop] Lever form mandates CGPA / 12th percentage / DOB / Address. Dropping internship.")
        return "dropped_demographics_required"

    file_input = page.query_selector('input[type="file"]')
    if file_input:
        try:
            file_input.set_input_files(str(resume_path))
            print(f"  [Upload] Attached tailored resume: {resume_path.name}")
            page.wait_for_timeout(1000)
        except Exception as e:
            print(f"  ! File upload warning: {e}")

    name_el = page.query_selector('input[name="name"]')
    if name_el: name_el.fill(personal.get("full_name", ""))

    email_el = page.query_selector('input[name="email"]')
    if email_el: email_el.fill(personal.get("email", ""))

    phone_el = page.query_selector('input[name="phone"]')
    if phone_el: phone_el.fill(personal.get("phone", ""))

    org_el = page.query_selector('input[name="org"]')
    if org_el: org_el.fill("Independent GenAI Developer / JECRC University")

    urls = page.query_selector_all('input[name*="urls"]')
    for u in urls:
        name_attr = u.get_attribute("name") or ""
        if "LinkedIn" in name_attr:
            u.fill(personal.get("linkedin", ""))
        elif "GitHub" in name_attr:
            u.fill(personal.get("github", ""))
        elif "Portfolio" in name_attr or "Other" in name_attr:
            u.fill(personal.get("portfolio", ""))

    # Additional textareas (cover letter, notes)
    for ta in page.query_selector_all('textarea'):
        if not ta.input_value():
            ta.fill(std_answers.get("why_hire_me", ""))

    return None


def fill_greenhouse_form(page, answers: Dict[str, Any], resume_path: Path) -> Optional[str]:
    """Fills standardized Greenhouse application forms."""
    if check_demographics_blocker(page):
        print("  [Policy Drop] Greenhouse form mandates CGPA / 12th percentage / DOB / Address. Dropping internship.")
        return "dropped_demographics_required"

    personal = answers.get("personal", {})
    std_answers = answers.get("standard_answers", {})
    name_parts = personal.get("full_name", "").split(" ", 1)

    fn = page.query_selector('input#first_name, input[name*="first_name"]')
    if fn: fn.fill(name_parts[0])
    ln = page.query_selector('input#last_name, input[name*="last_name"]')
    if ln: ln.fill(name_parts[1] if len(name_parts) > 1 else "")

    email = page.query_selector('input#email, input[name*="email"]')
    if email: email.fill(personal.get("email", ""))

    phone = page.query_selector('input#phone, input[name*="phone"]')
    if phone: phone.fill(personal.get("phone", ""))

    file_input = page.query_selector('input[type="file"]')
    if file_input:
        try:
            file_input.set_input_files(str(resume_path))
            print(f"  [Upload] Attached tailored resume: {resume_path.name}")
        except Exception as e:
            print(f"  ! File upload warning: {e}")

    for inp in page.query_selector_all('input[type="text"]'):
        label = ""
        id_val = inp.get_attribute("id")
        if id_val:
            lbl = page.query_selector(f'label[for="{id_val}"]')
            if lbl: label = lbl.inner_text().lower()
        if "linkedin" in label:
            inp.fill(personal.get("linkedin", ""))
        elif "github" in label:
            inp.fill(personal.get("github", ""))
        elif "website" in label or "portfolio" in label:
            inp.fill(personal.get("portfolio", ""))
        elif "experience" in label:
            inp.fill("1")
        elif "salary" in label or "compensation" in label or "stipend" in label:
            inp.fill("$2,000 / month")

    for ta in page.query_selector_all('textarea'):
        if not ta.input_value():
            ta.fill(std_answers.get("why_hire_me", ""))

    return None
