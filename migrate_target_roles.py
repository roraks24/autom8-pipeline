#!/usr/bin/env python3
"""
migrate_target_roles.py - Enforce Tier 1, 2, 3 Priority Role classification across jobs.db.

- Target 1: GenAI Engineer Intern / GenAI Developer Intern (Priority 1)
- Target 2: AI Engineer Intern / Applied AI Engineer Intern (Priority 2)
- Target 3: AI Agent / Agentic AI Engineer Intern (Priority 3)

Non-target roles (generic Python, Legal Ops, Video Editors, Marketing, etc.)
are marked status = 'non_target_role'.
"""

import sqlite3
from pathlib import Path
from target_roles import classify_role

DB_PATH = Path(__file__).resolve().parent / "jobs.db"

def migrate():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # Check and add columns if missing
    columns = [r[1] for r in cur.execute("PRAGMA table_info(jobs)").fetchall()]
    if "target_tier" not in columns:
        print("Adding target_tier column to jobs table...")
        cur.execute("ALTER TABLE jobs ADD COLUMN target_tier INTEGER")
    if "target_category" not in columns:
        print("Adding target_category column to jobs table...")
        cur.execute("ALTER TABLE jobs ADD COLUMN target_category TEXT")
    con.commit()

    rows = cur.execute("SELECT id, source, company, title, status FROM jobs").fetchall()
    print(f"Total jobs to classify: {len(rows)}")

    counts = {1: 0, 2: 0, 3: 0, "excluded": 0}

    for jid, src, comp, title, status in rows:
        tier, cat, is_target = classify_role(title)
        if is_target:
            counts[tier] += 1
            # Keep previous applied / staged status if present, otherwise ensure status is new
            new_status = status if status in ("applied", "staged_for_review") else "new"
            cur.execute("""
                UPDATE jobs 
                SET target_tier = ?, target_category = ?, status = ?
                WHERE id = ?
            """, (tier, cat, new_status, jid))
        else:
            counts["excluded"] += 1
            cur.execute("""
                UPDATE jobs 
                SET target_tier = NULL, target_category = NULL, status = 'non_target_role'
                WHERE id = ?
            """, (jid,))

    con.commit()
    print("\nMigration Complete:")
    print(f"  Tier 1 [GenAI Engineer / Developer]: {counts[1]}")
    print(f"  Tier 2 [AI Engineer / Applied AI]:   {counts[2]}")
    print(f"  Tier 3 [AI Agent / Agentic AI]:       {counts[3]}")
    print(f"  Non-Target Roles Excluded:           {counts['excluded']}")

if __name__ == "__main__":
    migrate()
