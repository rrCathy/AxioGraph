"""Query connected nodes to find targets for isolated nodes."""
import sqlite3, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

conn = sqlite3.connect(r'C:\newproject\AxioGraph\data\axiograph.db')
conn.row_factory = sqlite3.Row

for bid in ['401353c5-f45b-4008-b594-e2aa3261013a', 'a0eae8c3-916d-4ca7-a36f-a0bd38cd6617']:
    book = conn.execute('SELECT title FROM books WHERE id=?',(bid,)).fetchone()['title']
    print(f'\n=== Connected nodes in: {book} ({bid}) ===')
    nodes = conn.execute('''
        SELECT DISTINCT n.id, n.entity_type, n.name FROM graph_nodes n
        WHERE n.book_id = ? AND n.id IN (
            SELECT source_id FROM graph_edges UNION SELECT target_id FROM graph_edges
        ) AND n.entity_type IN ('THEOREM','DEFINITION','LEMMA','PROPOSITION','CONCEPT')
        ORDER BY n.entity_type, n.name
    ''', (bid,)).fetchall()
    for n in nodes:
        name = n['name'][:70]
        print(f'  {n["entity_type"]:12s} | {name} | id={n["id"]}')

conn.close()
