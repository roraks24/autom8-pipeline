import sqlite3

conn = sqlite3.connect('jobs.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()

c.execute("SELECT id, company, title, status, notes FROM jobs WHERE company IN ('Artefact', 'Bree Technologies (YC21)', 'BairesDev')")
for r in c.fetchall():
    print(r['company'], "->", r['status'], "|", r['notes'][:60] if r['notes'] else '')

conn.close()
