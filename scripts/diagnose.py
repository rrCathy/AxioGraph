"""Diagnose knowledge graph issues - outputs to file to avoid encoding issues."""
import sqlite3
import sys
import io

# Force UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DB = r'C:\newproject\AxioGraph\data\axiograph.db'

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

# 1. Book IDs
books = conn.execute('SELECT id, title FROM books').fetchall()
print('=== BOOKS ===')
for b in books:
    print(f'  id={b["id"]}  title={b["title"]}')

# 2. Duplicate nodes (exact match)
dups = conn.execute('''
    SELECT book_id, name, entity_type, COUNT(*) as cnt, GROUP_CONCAT(id) as ids
    FROM graph_nodes
    GROUP BY book_id, name
    HAVING cnt > 1
    ORDER BY cnt DESC
''').fetchall()
print('\n=== EXACT DUPLICATE NODES (same name) ===')
if dups:
    for d in dups:
        ids_list = d['ids'].split(',')
        print(f'  [{d["book_id"]}] name="{d["name"]}" ({d["entity_type"]}): count={d["cnt"]}, ids={ids_list}')
else:
    print('  None found (exact match)')

# 2b. Near-duplicate search
print('\n=== NEAR-DUPLICATE SEARCH ===')
near_dups_queries = [
    ("%阿贝尔%鲁菲尼%", "阿贝尔-鲁菲尼"),
    ("%解析开拓%", "解析开拓"),
    ("%Cauchy%不等式%", "Cauchy不等式"),
    ("%定理6%", "定理6"),
]
for pattern, label in near_dups_queries:
    rows = conn.execute(
        'SELECT id, name, entity_type, book_id FROM graph_nodes WHERE name LIKE ?',
        (pattern,)
    ).fetchall()
    if len(rows) > 1:
        print(f'  Near-duplicate group "{label}":')
        for r in rows:
            print(f'    id={r["id"]}  name="{r["name"]}"  type={r["entity_type"]}  book={r["book_id"]}')

# 3. Isolated nodes
isolated = conn.execute('''
    SELECT n.id, n.book_id, n.entity_type, n.name, n.chapter
    FROM graph_nodes n
    WHERE n.id NOT IN (
        SELECT source_id FROM graph_edges
        UNION
        SELECT target_id FROM graph_edges
    )
    ORDER BY n.book_id, n.entity_type, n.name
''').fetchall()

print(f'\n=== ISOLATED NODES (total={len(isolated)}) ===')
by_book = {}
for n in isolated:
    bid = n['book_id']
    by_book.setdefault(bid, []).append(n)

for bid, nodes in by_book.items():
    print(f'\n  Book: {bid} ({len(nodes)} nodes):')
    for n in nodes:
        name = n['name'][:60]
        ch = (n['chapter'] or '-')[:20]
        print(f'    {n["entity_type"]:12s} | {name:60s} | ch={ch} | id={n["id"]}')

# 4. Circular dependencies
print('\n=== CIRCULAR DEPENDENCIES ===')
cycles = conn.execute('''
    SELECT e1.id as id1, e2.id as id2, e1.source_id, e1.target_id,
           e1.relation_type as r1, e2.relation_type as r2,
           n1.name as src_name, n2.name as tgt_name, e1.book_id
    FROM graph_edges e1
    JOIN graph_edges e2 ON e1.source_id = e2.target_id AND e1.target_id = e2.source_id AND e1.id < e2.id
    JOIN graph_nodes n1 ON e1.source_id = n1.id
    JOIN graph_nodes n2 ON e1.target_id = n2.id
''').fetchall()
for c in cycles:
    print(f'  [{c["book_id"]}] {c["src_name"]} --[{c["r1"]}]--> {c["tgt_name"]}  (edge {c["id1"]})')
    print(f'  [{c["book_id"]}] {c["tgt_name"]} --[{c["r2"]}]--> {c["src_name"]}  (edge {c["id2"]})')
    print()

# 5. PROVES edges
print('\n=== PROVES EDGES (all) ===')
proves = conn.execute('''
    SELECT e.id, e.relation_type, e.description, e.book_id,
           s.name as src, s.entity_type as stype,
           t.name as tgt, t.entity_type as ttype
    FROM graph_edges e
    JOIN graph_nodes s ON e.source_id = s.id
    JOIN graph_nodes t ON e.target_id = t.id
    WHERE e.relation_type = 'PROVES'
    ORDER BY e.book_id, s.name
''').fetchall()
for p in proves:
    print(f'  [{p["book_id"]}] edge {p["id"]}: [{p["stype"]}] {p["src"][:40]} --PROVES--> [{p["ttype"]}] {p["tgt"][:40]}')

# 6. Relation type distribution
print('\n=== RELATION TYPES ===')
rels = conn.execute('''
    SELECT relation_type, COUNT(*) as cnt
    FROM graph_edges
    GROUP BY relation_type
    ORDER BY cnt DESC
''').fetchall()
for r in rels:
    print(f'  {r["relation_type"]}: {r["cnt"]} edges')

# 7. Connectivity stats per book
print('\n=== CONNECTIVITY STATS ===')
for b in books:
    bid = b['id']
    total = conn.execute('SELECT COUNT(*) as cnt FROM graph_nodes WHERE book_id = ?', (bid,)).fetchone()['cnt']
    connected = conn.execute('''
        SELECT COUNT(DISTINCT n.id) as cnt FROM graph_nodes n
        WHERE n.book_id = ? AND n.id IN (
            SELECT source_id FROM graph_edges UNION SELECT target_id FROM graph_edges
        )
    ''', (bid,)).fetchone()['cnt']
    isolated_cnt = total - connected
    edges_cnt = conn.execute('SELECT COUNT(*) as cnt FROM graph_edges WHERE book_id = ?', (bid,)).fetchone()['cnt']
    print(f'  {b["title"]}: {total} nodes, {edges_cnt} edges, {connected} connected, {isolated_cnt} isolated ({isolated_cnt*100//total if total else 0}%)')

conn.close()
