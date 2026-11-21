import sqlite3

conn = sqlite3.connect('jobs.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()

# Internshala applications submitted today (2026-11-19): IDs start with 35066 or 35067
c.execute("SELECT company, title, notes FROM jobs WHERE source='internshala' AND (notes LIKE '%35066%' OR notes LIKE '%35067%') ORDER BY rowid ASC")
rows = c.fetchall()
print(f"Total Internshala submitted today (2026-11-19): {len(rows)}")
for idx, r in enumerate(rows, 1):
    print(f" {idx:2d}. {r['company']:<35} | {r['title']:<30} | {r['notes']}")

conn.close()
