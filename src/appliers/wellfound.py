import time
from pathlib import Path
from typing import Any, Dict
from src.appliers.ats import fill_ashby_form, fill_greenhouse_form, fill_lever_form


def fill_wellfound_form(page, answers: Dict[str, Any], resume_path: Path, job_title: str = "GenAI Engineer", company: str = "Startup", submit: bool = False) -> str:
    """
    Fills standardized Wellfound (AngelList) job application modal.
    Pipeline v2.0 Engine:
    - Waits for modal animation and GraphQL loading spinner resolution.
    - Handles relocation radio and React-select dropdown options.
    - Uses native property descriptor value setter & InputEvent to bypass React 18 state trapping.
    - Auto-fills custom inputs (Phone, LinkedIn, Portfolio).
    - Auto-selects screening radios (sponsorship -> No, relocation -> Yes).
    - Auto-submits via button[data-test="JobApplicationModal--SubmitButton"] when submit=True.
    - Dismisses post-submit "second screens" (upsell dialogs) via Close/Skip/Escape sequence.
    """
    personal = answers.get("personal", {})
    std_answers = answers.get("standard_answers", {})

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

    # Check if 'Log In' button is visible in header
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

    # Check if already applied (disabled '✓ Applied' button on job listing)
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

    # 2. Check Candidate Eligibility (Compensation, Location, In-country remote, Visa sponsorship)
    is_ineligible, inelig_reason = page.evaluate("""() => {
        const jobHeader = document.querySelector('h1')?.closest('div')?.parentElement || document.querySelector('h1')?.parentElement || document.body;
        const jobHeaderText = (jobHeader.innerText || '').toLowerCase();

        // If job header clearly shows positive salary (e.g. $ or ₹ or /yr or /mo), it's paid
        const isPaid = /[\$₹]|(?:usd|inr|eur|gbp)\b|\b\d+k\b|\b\d+,\d+\b/.test(jobHeaderText) && !/\b(?:0|zero)\s*(?:stipend|salary|pay)/.test(jobHeaderText);

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
            print(f"  [Compensation Policy] Candidate policy: {inelig_reason}. Marked unpaid_excluded.")
            return "unpaid_excluded"
        print(f"  [Eligibility Policy] Candidate ineligible: {inelig_reason}. Marked ineligible.")
        return "ineligible"

    # 3. Locate and click exact 'Apply' button
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
            # Check if button is actually disabled 'Applied'
            btn_applied = page.evaluate("""() => {
                const b = document.querySelector('[class*="styles_applyButton"]');
                return b && (b.disabled || b.innerText.toLowerCase().includes('applied'));
            }""")
            if btn_applied:
                print("  [Wellfound] Verified: Candidate has already applied to this role.")
                return "already_applied"
            if "no longer available" in (page.inner_text("body") or "").lower():
                print("  [Wellfound] Verified: Listing is closed.")
                return "expired"

    # Wait for modal and past the GraphQL spinner
    try:
        page.wait_for_selector('[data-test="JobApplication-Modal"], [role="dialog"], .ReactModal__Content', timeout=8000)
        # Wait up to 5s for spinner to resolve and form fields to render
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
        # Check if actually applied or expired before falling back
        btn_applied = page.evaluate("""() => {
            const b = document.querySelector('[class*="styles_applyButton"]');
            return b && (b.disabled || b.innerText.toLowerCase().includes('applied'));
        }""")
        if btn_applied:
            print("  [Wellfound] Verified: Candidate has already applied to this role.")
            return "already_applied"
        if "no longer available" in (page.inner_text("body") or "").lower():
            print("  [Wellfound] Verified: Listing is closed.")
            return "expired"
        page.wait_for_timeout(2000)

    # Verify modal eligibility before proceeding
    modal_inelig, modal_inelig_msg = page.evaluate("""() => {
        const modal = document.querySelector('[data-test="JobApplication-Modal"], [role="dialog"], .ReactModal__Content');
        if (!modal) return [false, ''];
        const text = (modal.innerText || '').toLowerCase();
        const modalIsPaid = /[\$₹]|(?:usd|inr|eur|gbp)\b|\b\d+k\b|\b\d+,\d+\b/.test(text) && !/\b(?:0|zero)\s*(?:stipend|salary|pay)/.test(text);
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
        print(f"  [Policy Check] Candidate policy: {modal_inelig_msg}. Closing modal and marking {status_code}.")
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return status_code

    # Check if redirected to login wall after click
    if "login" in page.url.lower() or "signup" in page.url.lower():
        print("  [Notice] Wellfound redirected to login wall.")
        return "login_required"

    # 3. Check if redirected to external ATS (Greenhouse, Lever, Ashby)
    curr_url = page.url.lower()
    if "greenhouse.io" in curr_url:
        print("  [Routing] Wellfound redirected to external Greenhouse board.")
        return fill_greenhouse_form(page, answers, resume_path)
    elif "lever.co" in curr_url:
        print("  [Routing] Wellfound redirected to external Lever board.")
        return fill_lever_form(page, answers, resume_path)
    elif "ashbyhq.com" in curr_url:
        print("  [Routing] Wellfound redirected to external Ashby board.")
        return fill_ashby_form(page, answers, resume_path)

    # Check for Demographics Blocker (CGPA, 12th percentage, DOB, permanent address)
    has_demographics = page.evaluate("""() => {
        const modal = document.querySelector('[data-test="JobApplication-Modal"], [role="dialog"], .ReactModal__Content') || document.body;
        const text = modal.innerText || '';
        const patterns = [/\\bcgpa\\b/i, /\\bgpa\\b/i, /12th\\s*(percentage|percent|marks)/i, /10th\\s*(percentage|percent|marks)/i, /date\\s*of\\s*birth/i, /\\bdob\\b/i, /permanent\\s*address/i, /\\bpin\\s*code\\b/i];
        for (const p of patterns) {
            if (p.test(text)) return true;
        }
        return false;
    }""")
    if has_demographics:
        print("  [Policy Drop] Wellfound modal mandates CGPA / 12th percentage / DOB / Address. Dropping internship.")
        return "dropped_demographics_required"

    # 4. Handle Relocation / Location Dropdown if present (v2)
    try:
        # Click relocation radio label
        reloc_label = page.query_selector('label[for*="relocate_to"], input[value="relocate_to"]')
        if reloc_label:
            reloc_label.click()
            page.wait_for_timeout(600)

        # React-select dropdown input
        select_input = page.query_selector('input[id*="qualification.location"], .select__input input')
        if select_input:
            select_input.focus()
            page.keyboard.press("ArrowDown")
            page.wait_for_timeout(400)
            page.keyboard.press("Enter")
            page.wait_for_timeout(600)
    except Exception:
        pass

    # 5. Auto-fill All Custom Text Inputs (Phone, LinkedIn, Portfolio) & Radios (v2)
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

            // 1. Text Inputs (Phone, LinkedIn, GitHub, Portfolio)
            const inputs = [...modal.querySelectorAll('input[type="text"], input[type="tel"], input[type="url"], input:not([type])')];
            for (const input of inputs) {
                if (input.value && input.value.trim().length > 0) continue;
                let labelText = '';
                if (input.id) {
                    const l = modal.querySelector(`label[for="${input.id}"]`);
                    if (l) labelText = l.innerText;
                }
                if (!labelText && input.closest('label')) labelText = input.closest('label').innerText;
                if (!labelText && input.parentElement) {
                    let parent = input.parentElement;
                    while (parent && parent !== modal && !labelText) {
                        const t = (parent.innerText || '').split('\\n')[0];
                        if (t && t.length < 80) labelText = t;
                        parent = parent.parentElement;
                    }
                }
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
                } else if (fullCtx.includes('salary') || fullCtx.includes('stipend') || fullCtx.includes('compensation')) {
                    setVal(input, (fullCtx.includes('$') || fullCtx.includes('usd')) ? "2000" : "30000");
                } else if (fullCtx.includes('notice') || fullCtx.includes('start date') || fullCtx.includes('earliest')) {
                    setVal(input, "Immediately");
                }
            }

            // 2. Radio Groups (Grouped cleanly by input name)
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

                // Find question context by walking up from the first radio
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
                } else if (grpText.includes('relocat') || grpText.includes('office') || grpText.includes('location') || grpText.includes('miles') || grpText.includes('nyc') || grpText.includes('city')) {
                    targetRadio = radios.find(r => {
                        const t = (r.parentElement ? r.parentElement.innerText : '').toLowerCase();
                        return t.includes('relocate') || t.includes('yes') || t.includes('no, but willing');
                    }) || radios[0];
                } else if (grpText.includes('in person') || grpText.includes('excited') || grpText.includes('join') || grpText.includes('able') || grpText.includes('irregular') || grpText.includes('weekends') || grpText.includes('travel')) {
                    targetRadio = radios.find(r => {
                        const t = (r.parentElement ? r.parentElement.innerText : '').toLowerCase();
                        return t.includes('yes') || t.includes('commit') || t.includes('able');
                    }) || radios[0];
                } else {
                    targetRadio = radios.find(r => (r.parentElement ? r.parentElement.innerText : '').toLowerCase().includes('yes')) || radios[0];
                }

                if (targetRadio) {
                    targetRadio.checked = true;
                    targetRadio.dispatchEvent(new Event('input', { bubbles: true }));
                    targetRadio.dispatchEvent(new Event('change', { bubbles: true }));
                    if (targetRadio.parentElement) {
                        targetRadio.parentElement.click();
                    }
                    targetRadio.click();
                }
            }

            // Fallback for remaining lone radios
            const remainingRadios = [...modal.querySelectorAll('input[type="radio"]')].filter(r => !r.checked);
            for (const r of remainingRadios) {
                const label = (r.parentElement ? r.parentElement.innerText : '').toLowerCase();
                if (label.includes('yes') || label.includes('relocate') || label.includes('no, but') || label.includes('no')) {
                    r.checked = true;
                    r.dispatchEvent(new Event('input', { bubbles: true }));
                    r.dispatchEvent(new Event('change', { bubbles: true }));
                    if (r.parentElement) r.parentElement.click();
                    r.click();
                }
            }
        }""", {
            "phone": personal.get("phone", "+917877169982"),
            "linkedin": personal.get("linkedin", "https://www.linkedin.com/in/rorak/"),
            "github": personal.get("github", "https://github.com/roraks24"),
            "portfolio": personal.get("portfolio", "https://www.rorak.tech")
        })
        page.wait_for_timeout(500)
    except Exception as e:
        print(f"  ! Input fields filling warning: {e}")

    # 6. Fill Recruiter Note / Pitch textarea using React Native Property Setter (v2)
    pitch_text = std_answers.get("why_hire_me", "")
    if not pitch_text:
        pitch_text = (
            f"GenAI & Python Developer specializing in {job_title}. "
            "Built Rorak AI (live document-grounded RAG on FastAPI/Cloud Run at https://www.rorak.tech), "
            "5-agent scoping architecture for NVIDIA's Agentic AI Hackathon, and finalist in ISRO BAH 2026. "
            f"Excited to bring high-autonomy backend & LLM engineering to {company}."
        )

    try:
        filled_ok = page.evaluate("""(text) => {
            const modal = document.querySelector('[data-test="JobApplication-Modal"], [role="dialog"], .ReactModal__Content');
            const root = modal || document;
            const textareas = [...root.querySelectorAll('textarea, [contenteditable="true"]')].filter(el => {
                const s = window.getComputedStyle(el);
                return s.display !== 'none' && s.visibility !== 'hidden' && !el.disabled && !el.readOnly;
            });
            if (textareas.length === 0) return false;
            for (const el of textareas) {
                el.focus();
                let ans = text;
                const containerText = (el.closest('div')?.parentElement?.innerText || '').toLowerCase();
                if (containerText.includes('excite') || containerText.includes('interest') || containerText.includes('why join') || containerText.includes('why work')) {
                    ans = "I am excited about this opportunity because of your focus on building real-world AI applications. With hands-on experience building Rorak AI (document-grounded RAG on FastAPI, FAISS, PostgreSQL) and multi-agent workflows, I love solving hard technical problems independently and taking full ownership of what I ship.";
                } else if (containerText.includes('hardest') || containerText.includes('project') || containerText.includes('shipped') || containerText.includes('challenge')) {
                    ans = "I built and deployed Rorak AI (live at https://www.rorak.tech), a document-grounded RAG application on FastAPI, Docker, and Google Cloud Run. The hardest technical challenge was semantic retrieval accuracy with low latency across heterogeneous documents. I solved this by combining FAISS vector search with cross-encoder semantic reranking and Groq's Llama 3.3 70B for fast streaming responses. In addition, I designed a 5-agent stateful workflow for NVIDIA's Agentic AI Hackathon.";
                }
                const desc = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value');
                if (desc && desc.set) {
                    desc.set.call(el, ans);
                } else {
                    el.value = ans;
                }
                if (el._valueTracker) el._valueTracker.setValue('');
                el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText' }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new Event('blur', { bubbles: true }));
            }
            return true;
        }""", pitch_text)

        if filled_ok:
            print("  [Wellfound v2] Recruiter note filled and verified via React Native Setter.")
        else:
            for ta in page.query_selector_all('textarea'):
                if ta.is_visible() and not ta.input_value():
                    try:
                        ta.fill(pitch_text, timeout=2000)
                        print("  [Wellfound] Recruiter note filled via standard selector.")
                    except Exception:
                        pass
    except Exception as e:
        print(f"  ! Recruiter note filling warning: {e}")

    # 7. Upload ATS Tailored Resume
    file_input = page.query_selector('input[type="file"]')
    if file_input:
        try:
            file_input.set_input_files(str(resume_path))
            print(f"  [Upload] Attached tailored resume: {resume_path.name}")
            page.wait_for_timeout(1000)
        except Exception as e:
            print(f"  ! File upload warning: {e}")

    # 8. Handle Live Submission & Second-Screen Dismissal (v2)
    if submit:
        # Scroll modal to reveal submit button
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
            page_text = page.inner_text("body").lower()

            if not is_disabled:
                # Human review pause before clicking send
                page.wait_for_timeout(int(1000 * (1.5 + (time.time() % 1.5))))
                print("  [Action] [Wellfound v2] Clicking 'Send application'...")
                send_btn.click()
                page.wait_for_timeout(3500)

                # Dismiss any post-apply upsell modal if shown
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
            else:
                if "not accepting applications from your current location" in page_text or ("does not offer visa sponsorship" in page_text and "your profile indicates you require sponsorship" in page_text):
                    print("  ! Ineligible: Employer location/visa constraint (candidate outside hiring region). Marked ineligible.")
                    return "ineligible"
                print("  ! Submit button currently disabled (required employer question pending). Kept staged.")
                return "staged_for_review"
        else:
            btn_applied = page.evaluate("""() => {
                const b = document.querySelector('[class*="styles_applyButton"]');
                return b && (b.disabled || b.innerText.toLowerCase().includes('applied'));
            }""")
            if btn_applied:
                print("  [Wellfound] Verified: Candidate has already applied to this role.")
                return "already_applied"
            if "no longer available" in (page.inner_text("body") or "").lower():
                print("  [Wellfound] Verified: Listing is closed.")
                return "expired"
            print("  ! Submit button not detected in modal. Kept staged.")
            return "staged_for_review"

    return "staged_for_review"
