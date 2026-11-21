import os
import shutil
import time
import sqlite3
from pathlib import Path
from playwright.sync_api import sync_playwright

opera_dir = os.path.expanduser(r"~\AppData\Roaming\Opera Software\Opera GX Stable")
target_dir = os.path.expanduser(r"~\.chrome_job_profile")
os.makedirs(target_dir, exist_ok=True)

print("[1/3] Copying encryption keys (Local State)...")
src_state = os.path.join(opera_dir, "Local State")
dst_state = os.path.join(target_dir, "Local State")
try:
    shutil.copy2(src_state, dst_state)
    print("  -> Local State copied successfully.")
except Exception as e:
    print(f"  ! Warning: {e}")

src_cookies = os.path.join(opera_dir, "Default", "Network", "Cookies")
dst_cookies = os.path.join(target_dir, "Default", "Network", "Cookies")
os.makedirs(os.path.dirname(dst_cookies), exist_ok=True)

src_ls = os.path.join(opera_dir, "Default", "Local Storage")
dst_ls = os.path.join(target_dir, "Default", "Local Storage")

print("\n[2/3] Waiting for Opera GX to close (file lock release)...")
print(">>> LISTENER ACTIVE: PLEASE CLOSE OPERA GX FOR 5 SECONDS <<<", flush=True)

copied = False
for i in range(600):  # Wait up to 300s (5 minutes)
    try:
        shutil.copy2(src_cookies, dst_cookies)
        for ext in ["-wal", "-shm"]:
            if os.path.exists(src_cookies + ext):
                try: shutil.copy2(src_cookies + ext, dst_cookies + ext)
                except Exception: pass
        
        # Also copy Local Storage
        if os.path.exists(src_ls):
            try:
                if os.path.exists(dst_ls):
                    shutil.rmtree(dst_ls)
                shutil.copytree(src_ls, dst_ls)
            except Exception:
                pass
                
        copied = True
        break
    except PermissionError:
        time.sleep(0.5)

if not copied:
    print("[X] Timed out: Opera GX was not closed.")
    exit(1)

print("[OK] SUCCESS: Copied full browser session from Opera GX!", flush=True)

# Verify cookies count
try:
    con = sqlite3.connect(dst_cookies)
    rows = [r for r in con.execute("SELECT host_key, name FROM cookies").fetchall() if "internshala" in r[0]]
    print(f"  -> Verified {len(rows)} Internshala cookies stored in automated profile.", flush=True)
    con.close()
except Exception as e:
    print(f"  ! SQLite verify notice: {e}", flush=True)

print("\n[3/3] Verifying authenticated session in Playwright...", flush=True)
try:
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=target_dir,
            headless=True,
            viewport={"width": 1280, "height": 900}
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://internshala.com/student/dashboard", timeout=25000)
        page.wait_for_timeout(3000)
        content = page.content()
        page.screenshot(path="application_logs/opera_imported_verification.png")
        if "Rohit" in content or "rsaini2407@gmail.com" in content:
            print("[SUCCESS] Rohit Saini is fully logged into Internshala in the automation profile!", flush=True)
            print("YOU CAN NOW REOPEN OPERA GX ANYTIME.", flush=True)
        else:
            print(f"Landed on: {page.url} (Check application_logs/opera_imported_verification.png)", flush=True)
        ctx.close()
except Exception as e:
    print(f"Verification test error: {e}", flush=True)
