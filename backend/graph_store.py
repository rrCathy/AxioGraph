import json
import re
from database import get_db


def fix_unicode_escapes(text: str | None) -> str:
    """Convert literal \\u{XXXX} escapes (LLM output) to actual Unicode characters.
    Handles None, empty strings, and non-string types gracefully."""
    if not text or not isinstance(text, str):
        return text or ""
    return re.sub(r'\\u\{([0-9A-Fa-f]+)\}', lambda m: chr(int(m.group(1), 16)), text)


def sync_book_counts(conn, book_id: str):
    """Recompute the denormalized books.node_count / edge_count from real rows."""
    n = conn.execute("SELECT COUNT(*) FROM graph_nodes WHERE book_id = ?", (book_id,)).fetchone()[0]
    e = conn.execute("SELECT COUNT(*) FROM graph_edges WHERE book_id = ?", (book_id,)).fetchone()[0]
    conn.execute("UPDATE books SET node_count = ?, edge_count = ? WHERE id = ?", (n, e, book_id))


def _resolve_id(node_id: str, id_map: dict[str, str]) -> str:
    """Follow merge redirects; chains are possible when a batch has several duplicates."""
    seen = set()
    while node_id in id_map and node_id not in seen:
        seen.add(node_id)
        node_id = id_map[node_id]
    return node_id


def save_nodes_and_edges(nodes: list[dict], edges: list[dict], book_id: str):
    conn = get_db()
    id_map: dict[str, str] = {}
    for node in nodes:
        # Deduplicate: if node with same name+entity_type exists for this book,
        # merge content instead of creating duplicate
        existing = conn.execute(
            "SELECT id, content FROM graph_nodes WHERE book_id = ? AND name = ? AND entity_type = ?",
            (book_id, node["name"], node["entity_type"])
        ).fetchone()
        if existing and existing["id"] != node["id"]:
            # Merge: append new content to existing node, keep the existing id
            merged_content = existing["content"] or ""
            new_content = node.get("content", "")
            if new_content and new_content not in merged_content:
                merged_content = merged_content + "\n\n" + new_content
            conn.execute(
                "UPDATE graph_nodes SET content = ? WHERE id = ?",
                (merged_content, existing["id"])
            )
            # Remember the redirect so edges referencing node["id"] still land
            # on a real node instead of becoming dangling rows.
            id_map[node["id"]] = _resolve_id(existing["id"], id_map)
            continue

        conn.execute(
            """INSERT OR REPLACE INTO graph_nodes (id, book_id, entity_type, name, content, chapter)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (node["id"], node["book_id"], node["entity_type"], node["name"],
             node.get("content", ""), node.get("chapter", ""))
        )
    # Only ids that actually exist may be used as endpoints.
    valid_ids = {r[0] for r in conn.execute("SELECT id FROM graph_nodes")}
    for edge in edges:
        src = _resolve_id(edge["source_id"], id_map)
        tgt = _resolve_id(edge["target_id"], id_map)
        if src == tgt or src not in valid_ids or tgt not in valid_ids:
            # Self-loops and edges to missing nodes are dropped: Cytoscape rejects
            # them, and previously they persisted as dangling rows in SQLite.
            continue
        edge_book = edge.get("book_id", book_id)
        # Deduplicate: skip if same (source, target, relation_type) already exists for this book
        existing = conn.execute(
            "SELECT id FROM graph_edges WHERE source_id = ? AND target_id = ? AND relation_type = ? AND book_id = ?",
            (src, tgt, edge["relation_type"], edge_book)
        ).fetchone()
        if existing:
            continue
        conn.execute(
            """INSERT INTO graph_edges (source_id, target_id, relation_type, description, book_id)
               VALUES (?, ?, ?, ?, ?)""",
            (src, tgt, edge["relation_type"], edge.get("description", ""), edge_book)
        )
    sync_book_counts(conn, book_id)
    conn.commit()
    conn.close()


def get_graph_for_book(book_id: str) -> dict:
    """Return graph data in Cytoscape.js compatible format."""
    conn = get_db()
    nodes = conn.execute(
        "SELECT id, entity_type, name, content, chapter FROM graph_nodes WHERE book_id = ?",
        (book_id,)
    ).fetchall()
    edges = conn.execute(
        "SELECT id, source_id, target_id, relation_type, description FROM graph_edges WHERE book_id = ?",
        (book_id,)
    ).fetchall()
    conn.close()

    cy_nodes = []
    for n in nodes:
        ntype = n["entity_type"]
        colors = {
            "DEFINITION": "#4CAF50", "THEOREM": "#2196F3", "LEMMA": "#03A9F4",
            "COROLLARY": "#00BCD4", "AXIOM": "#F44336", "PROOF": "#9E9E9E",
            "EXAMPLE": "#FF9800", "CONCEPT": "#9C27B0",
        }
        cy_nodes.append({
            "data": {
                "id": n["id"],
                "label": f"[{ntype}] {fix_unicode_escapes(n['name'])}",
                "entity_type": ntype,
                "name": fix_unicode_escapes(n["name"]),
                "content": fix_unicode_escapes(n["content"])[:500],
                "chapter": fix_unicode_escapes(n["chapter"]),
                "color": colors.get(ntype, "#607D8B"),
            }
        })

    node_ids = {n["id"] for n in nodes}
    cy_edges = []
    for e in edges:
        if e["source_id"] not in node_ids or e["target_id"] not in node_ids:
            # Defensive: Cytoscape throws on edges with missing endpoints.
            continue
        cy_edges.append({
            "data": {
                "id": str(e["id"]),
                "source": e["source_id"],
                "target": e["target_id"],
                "label": e["relation_type"],
                "relation_type": e["relation_type"],
                "description": e["description"] or "",
            }
        })

    return {"elements": {"nodes": cy_nodes, "edges": cy_edges}}


def get_node_detail(node_id: str) -> dict | None:
    conn = get_db()
    node = conn.execute("SELECT * FROM graph_nodes WHERE id = ?", (node_id,)).fetchone()
    conn.close()
    if node:
        result = dict(node)
        # Fix unicode escapes in text fields
        for field in ("name", "content", "chapter", "metadata"):
            if field in result and result[field]:
                result[field] = fix_unicode_escapes(result[field])
        return result
    return None


def update_node(node_id: str, name: str, content: str):
    conn = get_db()
    conn.execute(
        "UPDATE graph_nodes SET name = ?, content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (name, content, node_id)
    )
    conn.commit()
    conn.close()


def delete_node(node_id: str):
    conn = get_db()
    row = conn.execute("SELECT book_id FROM graph_nodes WHERE id = ?", (node_id,)).fetchone()
    conn.execute("DELETE FROM graph_edges WHERE source_id = ? OR target_id = ?", (node_id, node_id))
    conn.execute("DELETE FROM graph_nodes WHERE id = ?", (node_id,))
    if row:
        sync_book_counts(conn, row["book_id"])
    conn.commit()
    conn.close()


def search_nodes(query: str, book_id: str | None = None) -> list[dict]:
    conn = get_db()
    if book_id:
        nodes = conn.execute(
            "SELECT * FROM graph_nodes WHERE book_id = ? AND (name LIKE ? OR content LIKE ?)",
            (book_id, f"%{query}%", f"%{query}%")
        ).fetchall()
    else:
        nodes = conn.execute(
            "SELECT * FROM graph_nodes WHERE name LIKE ? OR content LIKE ?",
            (f"%{query}%", f"%{query}%")
        ).fetchall()
    conn.close()
    return [dict(n) for n in nodes]


def get_context_for_qa(question: str, book_id: str | None = None, limit: int = 10) -> list[dict]:
    """Retrieve relevant graph nodes as context for QA."""
    import sqlite3
    conn = get_db()
    nodes = []

    # Strategy: extract keywords from question and match against node names
    if book_id:
        base_query = "SELECT * FROM graph_nodes WHERE book_id = ? AND {} LIMIT ?"
        base_args = [book_id]
    else:
        base_query = "SELECT * FROM graph_nodes WHERE {} LIMIT ?"
        base_args = []

    seen_ids = set()

    def _add_results(rows):
        for r in rows:
            if r["id"] not in seen_ids:
                nodes.append(r)
                seen_ids.add(r["id"])

    # 1. Try exact name substring matches (node name contained in question)
    # Extract potential entity names from question: split by spaces + Chinese punctuation
    import re
    tokens = [t.strip() for t in re.split(r'[\s,，。！？、：；\u201c\u201d\u2018\u2019\u300a\u300b\-\+\(\)\[\]（）《》]+', question) if len(t.strip()) >= 2]
    for token in tokens:
        if len(nodes) >= limit:
            break
        rows = conn.execute(
            base_query.format("name LIKE ? OR content LIKE ?"),
            [*(base_args), f"%{token}%", f"%{token}%", limit - len(nodes)]
        ).fetchall()
        _add_results(rows)

    # 2. For Chinese text, also try character n-grams (2-3 chars)
    if len(nodes) < limit:
        chinese_chars = re.findall(r'[\u4e00-\u9fff]+', question)
        for fragment in chinese_chars:
            if len(fragment) < 2:
                continue
            for i in range(len(fragment) - 1):
                bigram = fragment[i:i+2]
                rows = conn.execute(
                    base_query.format("name LIKE ?"),
                    [*(base_args), f"%{bigram}%", limit - len(nodes)]
                ).fetchall()
                _add_results(rows)
                if len(nodes) >= limit:
                    break
            if len(nodes) >= limit:
                break

    # 3. Fallback: search for question as substring of name/content
    if len(nodes) < limit:
        rows = conn.execute(
            base_query.format("name LIKE ? OR content LIKE ?"),
            [*(base_args), f"%{question}%", f"%{question}%", limit - len(nodes)]
        ).fetchall()
        _add_results(rows)

    conn.close()
    return [dict(n) for n in nodes[:limit]]
