"""One-time purge of the legacy Galois-theory book data.

Scope (user-approved 2026-11-12, see docs/sop/2026-11-12-incremental-prd.md):
  - book row 401353c5-f45b-4008-b594-e2aa3261013a (伽罗瓦理论-章璞) and every
    child row in graph_nodes / graph_edges / chapters / pages / candidates /
    action_log.
  - NOT touched: other books, data/books/*.pdf, old .bak files.

A timestamped backup of the database is written BEFORE any delete, via the
sqlite3 backup API (safe under WAL).
"""
import shutil
import sqlite3
import sys
import time
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "axiograph.db"
GALOIS_ID = "401353c5-f45b-4008-b594-e2aa3261013a"

TABLES = [
    "graph_edges", "graph_nodes", "chapters", "pages", "candidates",
    "action_log", "books",
]


def main() -> int:
    if not DB.exists():
        print(f"database missing: {DB}")
        return 1

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = DB.with_name(f"axiograph.db.bak-{stamp}-prepurge")
    src = sqlite3.connect(str(DB))
    dst = sqlite3.connect(str(backup))
    with dst:
        src.backup(dst)
    dst.close()
    print(f"backup written: {backup.name} ({backup.stat().st_size // 1024} KB)")

    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    exists = conn.execute(
        "SELECT 1 FROM books WHERE id = ?", (GALOIS_ID,)
    ).fetchone()
    if not exists:
        print("Galois book not found — nothing to purge (already clean).")
        conn.close()
        return 0

    counts = {}
    for table in TABLES:
        col = "id" if table == "books" else "book_id"
        cur = conn.execute(
            f"DELETE FROM {table} WHERE {col} = ?", (GALOIS_ID,)
        )
        counts[table] = cur.rowcount
    conn.commit()

    print("purged rows:", {k: v for k, v in counts.items() if v})
    left = conn.execute(
        "SELECT id, title, node_count, edge_count FROM books ORDER BY created_at"
    ).fetchall()
    for r in left:
        print("remaining book:", dict(r))
    total_nodes = conn.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()[0]
    total_edges = conn.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0]
    print(f"graph totals now: {total_nodes} nodes / {total_edges} edges")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
