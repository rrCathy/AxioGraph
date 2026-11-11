"""检查数据库中是否有节点内容"""
import sys, os
os.chdir(r'C:\newproject\AxioGraph\backend')
sys.path.insert(0, '.')
from database import init_db, get_db

init_db()
conn = get_db()

books = conn.execute(
    "SELECT id, title, language, status, node_count, edge_count FROM books"
).fetchall()

for b in books:
    print(f"Book: {b['id'][:8]}... | {b['title'][:50]:50s} | {b['language']} | "
          f"status={b['status'][:30]:30s} | {b['node_count']}n / {b['edge_count']}e")

if books:
    b = books[0]
    node = conn.execute(
        "SELECT id, entity_type, name, length(content) as clen, content "
        "FROM graph_nodes WHERE book_id=? LIMIT 1", (b['id'],)
    ).fetchone()
    if node:
        print(f"\nFirst node: [{node['entity_type']}] {node['name']}")
        print(f"  content length (DB): {node['clen']}")
        print(f"  content preview: {node['content'][:300]}...")
    else:
        print("\n*** NO NODES in database for this book! ***")

    # Check via graph_store.get_node_detail
    from graph_store import get_node_detail
    node = conn.execute(
        "SELECT id FROM graph_nodes WHERE book_id=? LIMIT 1", (b['id'],)
    ).fetchone()
    if node:
        detail = get_node_detail(node['id'])
        if detail:
            print(f"\nget_node_detail result:")
            print(f"  id: {detail.get('id', 'N/A')}")
            print(f"  name: {detail.get('name', 'N/A')}")
            print(f"  content length: {len(detail.get('content', ''))}")
            print(f"  content preview: {detail.get('content', '')[:150]}...")
        else:
            print("\n*** get_node_detail returned None! ***")
else:
    print("No books in database!")

conn.close()
