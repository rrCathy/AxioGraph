"""Quick check: remaining isolated nodes and Schwarz-Christoffel target."""
import sqlite3, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

conn = sqlite3.connect(r'C:\newproject\AxioGraph\data\axiograph.db')
conn.row_factory = sqlite3.Row
COMPLEX = 'a0eae8c3-916d-4ca7-a36f-a0bd38cd6617'

# Fix 1: Schwarz-Christoffel
r = conn.execute("SELECT id, name FROM graph_nodes WHERE book_id=? AND name LIKE '%Schwarz%Christoffel%'",
    (COMPLEX,)).fetchall()
print('Schwarz-Christoffel nodes:')
for row in r:
    print(f'  {row["id"]}: {row["name"][:80]}')

# Fix 2: Remaining isolated
iso = conn.execute('''
    SELECT n.id, n.entity_type, n.name, n.book_id FROM graph_nodes n
    WHERE n.id NOT IN (SELECT source_id FROM graph_edges UNION SELECT target_id FROM graph_edges)
    ORDER BY n.book_id, n.entity_type, n.name
''').fetchall()
print(f'\nRemaining isolated: {len(iso)}')
for n in iso:
    print(f'  [{n["id"][:8]}] {n["entity_type"]:12s} | {n["name"][:60]} | book={n["book_id"][:8]}')

# Fix 3: check if any edge still has cycles
print('\nCycles:')
cycles = conn.execute('''
    SELECT COUNT(*) as cnt FROM
    (SELECT e1.id FROM graph_edges e1
     JOIN graph_edges e2 ON e1.source_id = e2.target_id AND e1.target_id = e2.source_id AND e1.id < e2.id)
''').fetchone()['cnt']
print(f'  {cycles} cycles')

conn.close()
