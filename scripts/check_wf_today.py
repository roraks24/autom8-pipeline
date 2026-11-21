import sqlite3

conn = sqlite3.connect('jobs.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()

# Today's Wellfound applications
c.execute("""
    SELECT company, title, notes, url 
    FROM jobs 
    WHERE source='wellfound' 
      AND status='applied' 
      AND (rowid > (SELECT max(rowid) FROM jobs WHERE company='Dumbl'))
    ORDER BY rowid ASC
""")
rows = c.fetchall()
print(f"Total Wellfound applications applied: {len(rows)}")
for idx, r in enumerate(rows, 1):
    print(f" {idx:2d}. {r['company']:<35} | {r['title']}")

# How many jobs currently 'new' or 'staged_for_review' on Wellfound?
c.execute("SELECT count(*) FROM jobs WHERE source='wellfound' AND status='new'")
print(f"\nWellfound 'new' ready to apply: {c.fetchone()[0]}")

conn.close()
