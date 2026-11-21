import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright
from src.config import get_cookie_path

cookie_path = get_cookie_path("wellfound")
profile_dir = Path.home() / ".chrome_job_profile"

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        headless=True,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 900}
    )
    if cookie_path.exists():
        with open(cookie_path, "r", encoding="utf-8") as f:
            context.add_cookies(json.load(f))
    page = context.pages[0] if context.pages else context.new_page()

    test_url = "https://wellfound.com/jobs/4867012-embedded-software-engineer"
    page.goto(test_url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)

    # Let's see what triggered ineligibility
    body_text = page.inner_text("body").lower()
    
    triggers = []
    if "not accepting applications from your current location" in body_text:
        triggers.append("not accepting applications from your current location")
    if "does not offer visa sponsorship" in body_text:
        triggers.append("does not offer visa sponsorship")
    if "your profile indicates you require sponsorship" in body_text:
        triggers.append("your profile indicates you require sponsorship")
    if "must reside in the united states" in body_text:
        triggers.append("must reside in the united states")
    if "must reside in the uk" in body_text:
        triggers.append("must reside in the uk")
        
    print("Triggers found on page:", triggers)

    # Can we click Apply?
    apply_btn = page.query_selector('button:has-text("Apply"), [class*="styles_applyButton"]')
    print("Apply button found:", apply_btn is not None)
    if apply_btn:
        print("Apply button text:", apply_btn.inner_text())
        apply_btn.click()
        page.wait_for_timeout(2000)
        
        modal = page.query_selector('.ReactModal__Content, [data-test="JobApplication-Modal"]')
        print("Modal opened:", modal is not None)
        if modal:
            print("Modal text snippet:", modal.inner_text()[:300].replace('\n', ' '))
            send_btn = modal.query_selector('button:has-text("Send application"), button[data-test="JobApplicationModal--SubmitButton"]')
            print("Send button in modal:", send_btn is not None)
            if send_btn:
                print("Send button disabled?", send_btn.evaluate("b => b.disabled || b.getAttribute('aria-disabled')"))

    context.close()
