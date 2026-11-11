"""Inspect the knowledge graph for a specific book."""
import sys, os, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r'C:\newproject\AxioGraph\backend')
sys.path.insert(0, '.')

import sqlite3

conn = sqlite3.connect(r'C:\newproject\AxioGraph\data\axiograph.db')
BOOK_ID = '04cac5d3-1674-43ca-8dee-c2801a64ae87'

# Get book info
book = conn.execute("SELECT * FROM books WHERE id=?", (BOOK_ID,)).fetchone()
print(f"Book: {book[1]}")
print(f"Status: {book[4]}")
print()

# Node type counts
rows = conn.execute(
    "SELECT entity_type, COUNT(*) FROM graph_nodes WHERE book_id=? GROUP BY entity_type ORDER BY COUNT(*) DESC",
    (BOOK_ID,)
).fetchall()
print("Node types:")
for r in rows:
    print(f"  {r[0]:16s} {r[1]}")
print()

# Show all nodes with content
nodes = conn.execute(
    "SELECT entity_type, name, substr(content, 1, 200) as content_preview FROM graph_nodes WHERE book_id=? ORDER BY entity_type, name",
    (BOOK_ID,)
).fetchall()
print(f"Total nodes: {len(nodes)}")
print()

for n in nodes:
    print(f"[{n[0]:12s}] {n[1]}")
    print(f"     {n[2]}")
    print()

# Show all edges
edges = conn.execute(
    """SELECT gs.name as source_name, ge.relation_type, gt.name as target_name, substr(ge.description,1,80) as descr
       FROM graph_edges ge
       JOIN graph_nodes gs ON ge.source_id = gs.id
       JOIN graph_nodes gt ON ge.target_id = gt.id
       WHERE ge.book_id=?
       ORDER BY ge.relation_type""",
    (BOOK_ID,)
).fetchall()
print(f"Total edges: {len(edges)}")
print()
for e in edges:
    print(f"  {e[0][:40]:40s} --[{e[1]:14s}]--> {e[2][:40]}")
    if e[3]:
        print(f"    {e[3]}")

conn.close()
