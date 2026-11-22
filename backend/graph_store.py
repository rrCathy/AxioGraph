import json
import re
import time
import uuid
from database import get_db


def fix_unicode_escapes(text: str | None) -> str:
    """Convert literal \\u{XXXX} escapes (LLM output) to actual Unicode characters.
    Handles None, empty strings, and non-string types gracefully."""
    if not text or not isinstance(text, str):
        return text or ""
    return re.sub(r'\\u\{([0-9A-Fa-f]+)\}', lambda m: chr(int(m.group(1), 16)), text)


def sync_book_counts(conn, book_id: str):
    """Recompute the denormalized books.node_count / edge_count from real rows.
    Recycled (soft-deleted) items don't count — they are not in the graph."""
    n = conn.execute("SELECT COUNT(*) FROM graph_nodes WHERE book_id = ? AND deleted = 0", (book_id,)).fetchone()[0]
    e = conn.execute("SELECT COUNT(*) FROM graph_edges WHERE book_id = ? AND deleted = 0", (book_id,)).fetchone()[0]
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
    """Return graph data in Cytoscape.js compatible format. Recycled nodes
    and their cascaded edges are invisible."""
    conn = get_db()
    nodes = conn.execute(
        "SELECT id, entity_type, name, content, chapter, review_status, tags FROM graph_nodes WHERE book_id = ? AND deleted = 0",
        (book_id,)
    ).fetchall()
    edges = conn.execute(
        "SELECT id, source_id, target_id, relation_type, description, review_status FROM graph_edges WHERE book_id = ? AND deleted = 0",
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
                "review_status": n["review_status"] or "legacy",
                "tags": n["tags"] or "[]",
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
                "review_status": e["review_status"] or "legacy",
            }
        })

    return {"elements": {"nodes": cy_nodes, "edges": cy_edges}}


def get_node_detail(node_id: str) -> dict | None:
    conn = get_db()
    node = conn.execute(
        "SELECT * FROM graph_nodes WHERE id = ? AND deleted = 0", (node_id,)).fetchone()
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
        "UPDATE graph_nodes SET name = ?, content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND deleted = 0",
        (name, content, node_id)
    )
    conn.commit()
    conn.close()


def delete_node(node_id: str):
    """Single delete from the node inspector — soft delete into the recycle
    bin, cascading to the node's edges so a restore brings the pair back."""
    conn = get_db()
    row = conn.execute("SELECT book_id FROM graph_nodes WHERE id = ?", (node_id,)).fetchone()
    conn.execute(
        "UPDATE graph_edges SET deleted = 1, deleted_at = CURRENT_TIMESTAMP "
        "WHERE deleted = 0 AND (source_id = ? OR target_id = ?)", (node_id, node_id))
    conn.execute(
        "UPDATE graph_nodes SET deleted = 1, deleted_at = CURRENT_TIMESTAMP WHERE id = ?",
        (node_id,))
    if row:
        sync_book_counts(conn, row["book_id"])
    conn.commit()
    conn.close()


def search_nodes(query: str, book_id: str | None = None) -> list[dict]:
    conn = get_db()
    if book_id:
        nodes = conn.execute(
            "SELECT * FROM graph_nodes WHERE book_id = ? AND deleted = 0 AND (name LIKE ? OR content LIKE ?)",
            (book_id, f"%{query}%", f"%{query}%")
        ).fetchall()
    else:
        nodes = conn.execute(
            "SELECT * FROM graph_nodes WHERE deleted = 0 AND (name LIKE ? OR content LIKE ?)",
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
        base_query = "SELECT * FROM graph_nodes WHERE book_id = ? AND deleted = 0 AND {} LIMIT ?"
        base_args = [book_id]
    else:
        base_query = "SELECT * FROM graph_nodes WHERE deleted = 0 AND {} LIMIT ?"
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


# ── Promote / relations (human-reviewed node creation) ──────────────────────

VALID_ENTITY_TYPES = {
    "DEFINITION", "THEOREM", "LEMMA", "PROPOSITION", "COROLLARY",
    "AXIOM", "PROOF", "EXAMPLE", "CONCEPT", "REMARK", "CONJECTURE",
    "CLAIM", "FACT", "ASSUMPTION", "PRINCIPLE", "NOTATION", "CONVENTION",
    "PROBLEM", "EXERCISE", "WARNING",
}

VALID_RELATION_TYPES = {
    "DEPENDS_ON", "GENERALIZES", "PROVES", "BUILDS_ON", "EXAMPLE_OF",
}


def promote_node(book_id: str, entity_type: str, name: str, content: str,
                 quote: str | None, page_start: int | None,
                 page_end: int | None, relations: list[dict] | None = None) -> dict:
    """Direct human promotion into the graph: one confirmed node + its edges.

    The name is user-editable before this call, so editing happens in the
    dialog; this write is atomic (node + edges + undo log) and returns the
    action_log token for an 8-second undo window.
    """
    entity_type = (entity_type or "CONCEPT").upper()
    name = (name or "").strip()
    content = (content or "").strip()
    quote = (quote or "").strip()
    if not name:
        return {"ok": False, "error": "name is required"}
    if entity_type not in VALID_ENTITY_TYPES:
        entity_type = "CONCEPT"
    if page_end is None:
        page_end = page_start

    conn = get_db()
    before: dict = {}
    # Same name+type in this book -> merge content and extend the page span,
    # mirroring confirm_candidate so human and AI paths agree. A recycled
    # duplicate must not block a fresh create (the reader deleted it).
    existing = conn.execute(
        """SELECT id, content, page_start, page_end FROM graph_nodes
           WHERE book_id = ? AND name = ? AND entity_type = ? AND deleted = 0""",
        (book_id, name, entity_type),
    ).fetchone()
    if existing:
        node_id = existing["id"]
        before = {"content": existing["content"], "page_end": existing["page_end"]}
        merged = (existing["content"] or "")
        if content and content not in merged:
            merged = (merged + "\n\n" + content) if merged else content
        new_end = max(existing["page_end"] or 0, page_end or 0) or existing["page_end"]
        conn.execute(
            "UPDATE graph_nodes SET content = ?, page_end = ? WHERE id = ?",
            (merged, new_end, node_id),
        )
        action = "merged"
    else:
        node_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO graph_nodes
               (id, book_id, entity_type, name, content, chapter,
                page_start, page_end, review_status, source_quote, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?, 'human')""",
            (node_id, book_id, entity_type, name, content,
             f"p{page_start}-{page_end}" if page_start else "",
             page_start, page_end, quote),
        )
        action = "created"

    edge_ids = _insert_relations(conn, book_id, node_id, relations or [])
    before["edge_ids"] = edge_ids
    token = _log_promote(conn, book_id, action, node_id, before)
    sync_book_counts(conn, book_id)
    conn.commit()
    conn.close()
    return {"ok": True, "action": action, "node_id": node_id,
            "edges_added": len(edge_ids), "undo_token": token}


def _insert_relations(conn, book_id: str, source_id: str,
                      relations: list[dict]) -> list[int]:
    """Insert edges whose target already exists as a node; skip the rest."""
    added: list[int] = []
    for rel in relations:
        target_id = str(rel.get("target_id") or "").strip()
        rel_type = str(rel.get("relation_type") or rel.get("type") or "").strip().upper()
        note = str(rel.get("description") or rel.get("note") or "")[:300]
        if not target_id or not rel_type or target_id == source_id:
            continue
        if rel_type not in VALID_RELATION_TYPES:
            rel_type = "DEPENDS_ON"
        exists = conn.execute(
            "SELECT 1 FROM graph_nodes WHERE id = ? AND deleted = 0", (target_id,),
        ).fetchone()
        if not exists:
            continue
        dup = conn.execute(
            """SELECT id FROM graph_edges
               WHERE source_id = ? AND target_id = ? AND relation_type = ? AND book_id = ?""",
            (source_id, target_id, rel_type, book_id),
        ).fetchone()
        if dup:
            continue
        cur = conn.execute(
            """INSERT INTO graph_edges
               (source_id, target_id, relation_type, description, book_id, review_status)
               VALUES (?, ?, ?, ?, ?, 'confirmed')""",
            (source_id, target_id, rel_type, note, book_id),
        )
        added.append(cur.lastrowid)
    return added


def _log_promote(conn, book_id: str, action: str, node_id: str,
                 before: dict) -> str:
    token = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO action_log
           (token, book_id, action, candidate_id, node_id, before_json, expires_at)
           VALUES (?, ?, ?, NULL, ?, ?, ?)""",
        (token, book_id, action, node_id,
         json.dumps(before, ensure_ascii=False), time.time() + 8),
    )
    return token


def undo_promote(token: str) -> bool:
    """Undo a promote_node action within its 8-second window."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM action_log WHERE token = ?", (token,)).fetchone()
    if not row or row["undone"] or row["expires_at"] < time.time():
        conn.close()
        return False
    before = json.loads(row["before_json"] or "{}")
    edge_ids = before.get("edge_ids") or []
    if row["action"] == "created":
        conn.execute("DELETE FROM graph_edges WHERE source_id = ? OR target_id = ?",
                     (row["node_id"], row["node_id"]))
        conn.execute("DELETE FROM graph_nodes WHERE id = ?", (row["node_id"],))
    elif row["action"] == "merged":
        conn.execute(
            "UPDATE graph_nodes SET content = ?, page_end = ? WHERE id = ?",
            (before.get("content"), before.get("page_end"), row["node_id"]))
        for eid in edge_ids:
            conn.execute("DELETE FROM graph_edges WHERE id = ?", (eid,))
    conn.execute("UPDATE action_log SET undone = 1 WHERE token = ?", (token,))
    sync_book_counts(conn, row["book_id"])
    conn.commit()
    conn.close()
    return True


def add_edge(book_id: str, source_id: str, target_id: str,
             relation_type: str, description: str = "") -> dict | None:
    """Manual relation insert between two existing nodes."""
    relation_type = (relation_type or "").strip().upper()
    if relation_type not in VALID_RELATION_TYPES:
        return {"ok": False, "error": f"invalid relation_type: {relation_type}"}
    if not source_id or not target_id or source_id == target_id:
        return {"ok": False, "error": "invalid endpoints"}
    conn = get_db()
    missing = [nid for nid in (source_id, target_id)
               if not conn.execute("SELECT 1 FROM graph_nodes WHERE id = ? AND deleted = 0",
                                   (nid,)).fetchone()]
    if missing:
        conn.close()
        return {"ok": False, "error": f"node not found: {missing[0]}"}
    dup = conn.execute(
        """SELECT id FROM graph_edges
           WHERE source_id = ? AND target_id = ? AND relation_type = ? AND book_id = ?""",
        (source_id, target_id, relation_type, book_id),
    ).fetchone()
    if dup:
        conn.close()
        return {"ok": True, "edge_id": dup["id"], "deduped": True}
    cur = conn.execute(
        """INSERT INTO graph_edges
           (source_id, target_id, relation_type, description, book_id, review_status)
           VALUES (?, ?, ?, ?, ?, 'confirmed')""",
        (source_id, target_id, relation_type, (description or "")[:300], book_id),
    )
    sync_book_counts(conn, book_id)
    conn.commit()
    conn.close()
    return {"ok": True, "edge_id": cur.lastrowid, "deduped": False}


def delete_edge(edge_id: int) -> bool:
    conn = get_db()
    row = conn.execute("SELECT book_id FROM graph_edges WHERE id = ?",
                       (edge_id,)).fetchone()
    if not row:
        conn.close()
        return False
    conn.execute("DELETE FROM graph_edges WHERE id = ?", (edge_id,))
    sync_book_counts(conn, row["book_id"])
    conn.commit()
    conn.close()
    return True


def list_nodes_for_relation(book_id: str, exclude_id: str | None = None,
                            limit: int = 200) -> list[dict]:
    """Confirmed nodes as candidate relation targets (id/name/type/page)."""
    conn = get_db()
    rows = conn.execute(
        """SELECT id, name, entity_type, page_start, page_end FROM graph_nodes
           WHERE book_id = ? AND review_status = 'confirmed' AND deleted = 0 AND id != ?
           ORDER BY page_start, name LIMIT ?""",
        (book_id, exclude_id or "", limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Graph management: tags + soft delete (recycle bin) ──────────────────────


def batch_delete_nodes(book_id: str, node_ids: list[str]) -> dict:
    """Soft-delete nodes and cascade to their live edges (recycle bin).

    Returns the ids actually hidden, so the frontend's undo can restore
    exactly this set.
    """
    if not node_ids:
        return {"ok": True, "deleted": []}
    conn = get_db()
    deleted: list[str] = []
    for nid in node_ids:
        row = conn.execute(
            "SELECT id FROM graph_nodes WHERE id = ? AND book_id = ? AND deleted = 0",
            (nid, book_id),
        ).fetchone()
        if not row:
            continue
        conn.execute(
            "UPDATE graph_nodes SET deleted = 1, deleted_at = CURRENT_TIMESTAMP WHERE id = ?",
            (nid,))
        conn.execute(
            "UPDATE graph_edges SET deleted = 1, deleted_at = CURRENT_TIMESTAMP "
            "WHERE deleted = 0 AND (source_id = ? OR target_id = ?)", (nid, nid))
        deleted.append(nid)
    sync_book_counts(conn, book_id)
    conn.commit()
    conn.close()
    return {"ok": True, "deleted": deleted}


def restore_nodes(node_ids: list[str]) -> dict:
    """Undo of a delete: bring nodes back, plus their soft-deleted edges
    — but only edges whose BOTH endpoints are live again."""
    if not node_ids:
        return {"ok": True, "restored": []}
    conn = get_db()
    restored: list[str] = []
    for nid in node_ids:
        row = conn.execute(
            "SELECT id FROM graph_nodes WHERE id = ? AND deleted = 1", (nid,)
        ).fetchone()
        if not row:
            continue
        conn.execute(
            "UPDATE graph_nodes SET deleted = 0, deleted_at = NULL WHERE id = ?",
            (nid,))
        restored.append(nid)
    if restored:
        marks = ",".join("?" for _ in restored)
        conn.execute(
            f"""UPDATE graph_edges SET deleted = 0, deleted_at = NULL
                WHERE deleted = 1
                  AND source_id IN ({marks})
                  AND target_id IN (SELECT id FROM graph_nodes WHERE deleted = 0)""",
            (*restored,)),
        # edges whose OTHER end is still recycled stay hidden until that
        # node is restored too — the query above re-runs on its restore.
    books = [r["book_id"] for r in conn.execute(
        "SELECT DISTINCT book_id FROM graph_nodes WHERE id IN ({})".format(
            ",".join("?" for _ in restored)), (*restored,)).fetchall()]
    for b in books:
        sync_book_counts(conn, b)
    conn.commit()
    conn.close()
    return {"ok": True, "restored": restored}


def purge_nodes(node_ids: list[str]) -> dict:
    """Hard delete from the recycle bin: gone for good."""
    if not node_ids:
        return {"ok": True, "purged": 0}
    conn = get_db()
    books = [r["book_id"] for r in conn.execute(
        "SELECT DISTINCT book_id FROM graph_nodes WHERE id IN ({})".format(
            ",".join("?" for _ in node_ids)), (*node_ids,)).fetchall()]
    for nid in node_ids:
        conn.execute("DELETE FROM graph_edges WHERE source_id = ? OR target_id = ?",
                     (nid, nid))
        conn.execute("DELETE FROM graph_nodes WHERE id = ?", (nid,))
    for b in books:
        sync_book_counts(conn, b)
    conn.commit()
    conn.close()
    return {"ok": True, "purged": len(node_ids)}


def purge_all(book_id: str) -> dict:
    conn = get_db()
    node_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM graph_nodes WHERE book_id = ? AND deleted = 1", (book_id,))]
    conn.close()
    return purge_nodes(node_ids)


def list_recycle(book_id: str) -> dict:
    conn = get_db()
    nodes = conn.execute(
        """SELECT id, entity_type, name, page_start, page_end, review_status,
                  created_by, deleted_at
           FROM graph_nodes
           WHERE book_id = ? AND deleted = 1 ORDER BY deleted_at DESC""",
        (book_id,),
    ).fetchall()
    edges = conn.execute(
        """SELECT e.id, e.relation_type, e.description, e.deleted_at,
                  s.name AS source_name, t.name AS target_name
           FROM graph_edges e
           JOIN graph_nodes s ON s.id = e.source_id
           JOIN graph_nodes t ON t.id = e.target_id
           WHERE e.book_id = ? AND e.deleted = 1 AND s.deleted = 0 AND t.deleted = 0
           ORDER BY e.deleted_at DESC""",
        (book_id,),
    ).fetchall()
    conn.close()
    return {"nodes": [dict(r) for r in nodes], "edges": [dict(r) for r in edges]}


def _validate_tags(tags: list[dict]) -> list[dict]:
    """Normalise [{g,v}] label pairs; unknown groups are custom groups."""
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for t in tags or []:
        if not isinstance(t, dict):
            continue
        g = str(t.get("g") or "").strip()[:30]
        v = str(t.get("v") or "").strip()[:40]
        if not g or not v or (g, v) in seen:
            continue
        seen.add((g, v))
        out.append({"g": g, "v": v})
    return out


def set_node_tags(node_id: str, tags: list[dict]) -> dict:
    conn = get_db()
    row = conn.execute(
        "SELECT book_id FROM graph_nodes WHERE id = ? AND deleted = 0",
        (node_id,)).fetchone()
    if not row:
        conn.close()
        return {"ok": False, "error": "node not found"}
    conn.execute("UPDATE graph_nodes SET tags = ? WHERE id = ?",
                 (json.dumps(_validate_tags(tags), ensure_ascii=False), node_id))
    conn.commit()
    conn.close()
    return {"ok": True, "node_id": node_id}


def batch_add_tags(book_id: str, node_ids: list[str],
                   add_tags: list[dict]) -> dict:
    """Merge labels into each node's existing set (batch select → label)."""
    add = _validate_tags(add_tags)
    if not add or not node_ids:
        return {"ok": True, "updated": 0}
    conn = get_db()
    updated = 0
    for nid in node_ids:
        row = conn.execute(
            "SELECT tags FROM graph_nodes WHERE id = ? AND book_id = ? AND deleted = 0",
            (nid, book_id)).fetchone()
        if not row:
            continue
        try:
            cur = json.loads(row["tags"] or "[]")
        except Exception:
            cur = []
        merged = {f'{t.get("g")}\x1f{t.get("v")}' for t in _validate_tags(cur)}
        for t in add:
            merged.add(f'{t["g"]}\x1f{t["v"]}')
        out = [{"g": k.split("\x1f")[0], "v": k.split("\x1f")[1]} for k in sorted(merged)]
        conn.execute("UPDATE graph_nodes SET tags = ? WHERE id = ?",
                     (json.dumps(out, ensure_ascii=False), nid))
        updated += 1
    conn.commit()
    conn.close()
    return {"ok": True, "updated": updated}


def tag_list(book_id: str) -> dict:
    """All labels in use for this book, grouped — feeds the filter chips
    and the editor's suggestions."""
    conn = get_db()
    rows = conn.execute(
        "SELECT tags FROM graph_nodes WHERE book_id = ? AND deleted = 0",
        (book_id,)).fetchall()
    conn.close()
    groups: dict[str, list[str]] = {}
    for r in rows:
        try:
            tags = json.loads(r["tags"] or "[]")
        except Exception:
            continue
        for t in tags if isinstance(tags, list) else []:
            g, v = str(t.get("g", "")), str(t.get("v", ""))
            if g and v and v not in groups.setdefault(g, []):
                groups[g].append(v)
    return {"groups": groups}
