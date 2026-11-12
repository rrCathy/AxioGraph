"""Extract 1-3 page windows into reviewable candidates, then let a human
confirm them into the graph with page provenance.

Nothing from the LLM is written to graph_nodes until confirm_candidate() runs.
"""
import difflib
import json
import logging
import re
import threading
import time
import uuid

import json_repair

from database import get_db
from extractor import _is_substantial_node
from graph_store import sync_book_counts
from services.llm import get_llm
import page_service as ps

log = logging.getLogger("axiograph.extract")

# Cooperative cancellation for long extraction calls. AbortController on the
# client only kills the HTTP request; this flag stops the server from writing.
_cancel_events: dict[str, threading.Event] = {}
_cancel_lock = threading.Lock()


def register_task(task_id: str) -> None:
    with _cancel_lock:
        _cancel_events[task_id] = threading.Event()


def cancel_task(task_id: str) -> bool:
    with _cancel_lock:
        event = _cancel_events.get(task_id)
    if event is None:
        return False
    event.set()
    return True


def is_cancelled(task_id: str | None) -> bool:
    if not task_id:
        return False
    with _cancel_lock:
        event = _cancel_events.get(task_id)
    return bool(event and event.is_set())


def clear_task(task_id: str | None) -> None:
    if not task_id:
        return
    with _cancel_lock:
        _cancel_events.pop(task_id, None)

PAGE_PROMPT = """你是数学文献分析专家。下面是从 PDF 第 {start}-{end} 页提取的文本，每段以 [pN] 开头标记页码。
请提取其中有明确定义、定理陈述或证明的数学实体，作为**候选**供人工确认。原文可能有识别错误，宁可少提也不要编造。

规则：
1. 只提取本页窗口内出现且内容完整的实体。若某实体从上一页延续、本页只有后半部分，标 "continues": true 并在 content 里说明缺前半部分。
2. name 必须是有意义的完整名称（如"Cauchy 积分定理""解析开拓"），禁止裸符号 $G$、$f(x)$、纯编号"定理6"、泛称"群""定理"。
3. content 必须是结构化对象：定理用 {{"statement": "...", "proof": "..."}}，定义用 {{"definition": "...", "explanation": "..."}}，例题用 {{"problem": "...", "solution": "..."}}。数学公式用 $...$ 包裹。
4. quote：从原文摘一小段最能代表该实体的文字（不超过 200 字），供人工核对；必须是原文里真实出现的句子。
5. relations：该实体依赖/证明/例证的其他概念，用 {{"target": "概念名", "type": "DEPENDS_ON|PROVES|GENERALIZES|EXAMPLE_OF|BUILDS_ON", "note": "简短理由"}}。没有就给空数组。
6. 目录页、前言、页眉页脚、习题答案等无实质数学内容的文本，输出 []。
7. 本窗口最多提取 8 个实体，优先重要的定义与定理。

只输出严格 JSON 数组，格式：
[
  {{
    "entity": {{"type": "THEOREM", "name": "...", "content": {{"statement": "...", "proof": "..."}}, "quote": "...", "continues": false}},
    "relations": [{{"target": "...", "type": "DEPENDS_ON", "note": "..."}}]
  }}
]

页码范围：{start}-{end}
原文：
{text}
"""


def _parse_items(response: str) -> tuple[list[dict], bool]:
    """Return (items, parsed_ok). json-repair is the last resort for models
    that emit slightly broken JSON instead of a strict array."""
    if not response or not response.strip():
        return [], False
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "",
                  response.strip(), flags=re.I | re.M).strip()
    candidates = []
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        candidates.append(match.group())
    candidates.append(text)
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, list):
                return [x for x in data if isinstance(x, dict)], True
            if isinstance(data, dict) and isinstance(data.get("entities"), list):
                return [x for x in data["entities"] if isinstance(x, dict)], True
        except json.JSONDecodeError:
            continue
    try:
        data = json_repair.loads(text)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)], True
        if isinstance(data, dict) and isinstance(data.get("entities"), list):
            return [x for x in data["entities"] if isinstance(x, dict)], True
    except Exception:
        log.exception("json-repair failed on extraction output")
    return [], False


def extract_window(book_id: str, start: int, end: int,
                   task_id: str | None = None) -> dict:
    if end < start or end - start > 2:
        raise ValueError("window must be 1-3 pages")
    text = ps.window_text(book_id, start, end)
    if not text.strip():
        return {"candidates": [], "reason": "no text in this window"}

    prompt = (PAGE_PROMPT
              .replace("{start}", str(start))
              .replace("{end}", str(end))
              .replace("{text}", text[:12000]))
    messages = [
        {"role": "system", "content": "You extract mathematical entities as strict JSON. "
                                      "Never invent content. Output only a JSON array."},
        {"role": "user", "content": prompt},
    ]
    items: list[dict] = []
    parsed_ok = False
    for attempt in range(2):
        response = get_llm("extraction").chat(messages, temperature=0.1, max_tokens=4096)
        items, parsed_ok = _parse_items(response)
        if parsed_ok:
            break
        log.warning("unparseable extraction output (attempt %d/2): %r",
                    attempt + 1, (response or "")[:200])
    if not parsed_ok:
        log.error("extraction produced no JSON for pages %s-%s", start, end)

    # Nothing is written until the LLM returns AND the client has not cancelled.
    if is_cancelled(task_id):
        clear_task(task_id)
        return {"cancelled": True, "candidates": [], "raw_count": len(items),
                "pages": [start, end]}

    conn = get_db()
    saved = []
    for item in items:
        if not isinstance(item, dict):
            continue
        entity = item.get("entity", {}) or {}
        name = str(entity.get("name", "")).strip()
        content = entity.get("content", "")
        content_str = (json.dumps(content, ensure_ascii=False)
                       if isinstance(content, dict) else str(content).strip())
        if not _is_substantial_node(name, content_str):
            continue
        cid = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO candidates
               (id, book_id, page_start, page_end, entity_type, name,
                content, quote, relations_json, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
            (cid, book_id, start, end, str(entity.get("type", "CONCEPT")).upper(),
             name, content_str, str(entity.get("quote", ""))[:400],
             json.dumps(item.get("relations", []), ensure_ascii=False)),
        )
        saved.append({"id": cid, "name": name,
                      "type": str(entity.get("type", "CONCEPT")).upper(),
                      "quote": str(entity.get("quote", ""))[:120],
                      "continues": bool(entity.get("continues", False))})
    conn.commit()
    conn.close()
    clear_task(task_id)
    return {"candidates": saved, "raw_count": len(items), "pages": [start, end],
            "task_id": task_id}


def list_candidates(book_id: str, status: str = "pending") -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM candidates WHERE book_id = ? AND status = ? ORDER BY created_at DESC",
        (book_id, status),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["relations"] = json.loads(d.pop("relations_json") or "[]")
        out.append(d)
    return out


def _match_target(conn, book_id: str, target: str) -> str | None:
    names = {
        r["name"]: r["id"]
        for r in conn.execute(
            "SELECT id, name FROM graph_nodes WHERE book_id = ? AND review_status = 'confirmed'",
            (book_id,),
        )
    }
    if target in names:
        return names[target]
    close = difflib.get_close_matches(target, list(names), n=1, cutoff=0.85)
    return names[close[0]] if close else None


def _relation_lists(conn, book_id: str, relations_json: str) -> tuple[list[dict], list[dict]]:
    """Split relations into those that resolve to a confirmed node and those
    that would otherwise be silently discarded."""
    matched, dropped = [], []
    for rel in json.loads(relations_json or "[]"):
        item = {
            "target": str(rel.get("target", "")).strip(),
            "type": str(rel.get("type", "DEPENDS_ON")).upper(),
            "note": str(rel.get("note", ""))[:300],
        }
        if not item["target"]:
            continue
        target_id = _match_target(conn, book_id, item["target"])
        (matched if target_id else dropped).append({**item, "target_id": target_id})
    return matched, dropped


def _add_relations(conn, book_id: str, node_id: str, relations_json: str) -> tuple[int, list[dict]]:
    matched, dropped = _relation_lists(conn, book_id, relations_json)
    added = 0
    for rel in matched:
        target_id = rel["target_id"]
        if not target_id or target_id == node_id:
            continue
        exists = conn.execute(
            """SELECT id FROM graph_edges WHERE source_id = ? AND target_id = ?
               AND relation_type = ? AND book_id = ?""",
            (node_id, target_id, rel["type"], book_id),
        ).fetchone()
        if exists:
            continue
        conn.execute(
            """INSERT INTO graph_edges
               (source_id, target_id, relation_type, description, book_id, review_status)
               VALUES (?, ?, ?, ?, ?, 'confirmed')""",
            (node_id, target_id, rel["type"], rel["note"], book_id),
        )
        added += 1
    return added, dropped


def _log_action(conn, book_id: str, action: str, candidate_id: str,
                node_id: str | None, before: dict) -> str:
    token = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO action_log
           (token, book_id, action, candidate_id, node_id, before_json, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (token, book_id, action, candidate_id, node_id,
         json.dumps(before, ensure_ascii=False), time.time() + 8),
    )
    return token


def confirm_candidate(candidate_id: str, name_override: str | None = None,
                      quote_override: str | None = None) -> dict | None:
    conn = get_db()
    c = conn.execute("SELECT * FROM candidates WHERE id = ?", (candidate_id,)).fetchone()
    if not c:
        conn.close()
        return None
    if c["status"] != "pending":
        conn.close()
        return {"skipped": True, "status": c["status"]}

    name = (name_override or c["name"]).strip()
    quote = (quote_override or c["quote"] or "").strip()
    book_id = c["book_id"]
    before: dict = {}

    existing = conn.execute(
        """SELECT id, content, page_end FROM graph_nodes
           WHERE book_id = ? AND name = ? AND entity_type = ?
             AND review_status = 'confirmed'""",
        (book_id, name, c["entity_type"]),
    ).fetchone()
    if existing:
        node_id = existing["id"]
        before = {"content": existing["content"], "page_end": existing["page_end"]}
        merged_content = (existing["content"] or "") + "\n\n" + (c["content"] or "")
        conn.execute("UPDATE graph_nodes SET content = ?, page_end = ? WHERE id = ?",
                     (merged_content, c["page_end"], node_id))
        conn.execute("UPDATE candidates SET status = 'merged', merged_into = ? WHERE id = ?",
                     (node_id, candidate_id))
        action = "merged"
    else:
        node_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO graph_nodes
               (id, book_id, entity_type, name, content, chapter,
                page_start, page_end, review_status, source_quote, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?, 'human')""",
            (node_id, book_id, c["entity_type"], name, c["content"],
             f"p{c['page_start']}-{c['page_end']}",
             c["page_start"], c["page_end"], quote),
        )
        conn.execute("UPDATE candidates SET status = 'confirmed' WHERE id = ?", (candidate_id,))
        action = "created"

    edges, dropped = _add_relations(conn, book_id, node_id, c["relations_json"])
    conn.execute("UPDATE candidates SET dropped_relations_json = ? WHERE id = ?",
                 (json.dumps(dropped, ensure_ascii=False), candidate_id))
    token = _log_action(conn, book_id, action, candidate_id, node_id, before)
    sync_book_counts(conn, book_id)
    conn.commit()
    conn.close()
    return {"ok": True, "action": action, "node_id": node_id,
            "edges_added": edges, "relations_dropped": len(dropped),
            "undo_token": token}


def preview_candidate(candidate_id: str) -> dict | None:
    """Dry-run: show merge target and relations that would be dropped, without
    touching the database."""
    conn = get_db()
    c = conn.execute("SELECT * FROM candidates WHERE id = ?", (candidate_id,)).fetchone()
    if not c:
        conn.close()
        return None
    twin = conn.execute(
        """SELECT id, name, page_end FROM graph_nodes
           WHERE book_id = ? AND name = ? AND entity_type = ?
             AND review_status = 'confirmed'""",
        (c["book_id"], c["name"], c["entity_type"]),
    ).fetchone()
    matched, dropped = _relation_lists(conn, c["book_id"], c["relations_json"])
    conn.close()
    return {
        "action": "merged" if twin else "created",
        "merge_target": twin["name"] if twin else None,
        "page_end_after": c["page_end"],
        "relations_matched": [r["target"] for r in matched],
        "relations_dropped": dropped,
    }


def undo_action(token: str) -> bool:
    conn = get_db()
    row = conn.execute("SELECT * FROM action_log WHERE token = ?", (token,)).fetchone()
    if not row or row["undone"] or row["expires_at"] < time.time():
        conn.close()
        return False
    before = json.loads(row["before_json"] or "{}")
    action = row["action"]

    if action == "created":
        conn.execute("DELETE FROM graph_edges WHERE source_id = ? OR target_id = ?",
                     (row["node_id"], row["node_id"]))
        conn.execute("DELETE FROM graph_nodes WHERE id = ?", (row["node_id"],))
    elif action in ("merged", "merge"):
        conn.execute("UPDATE graph_nodes SET content = ?, page_end = ? WHERE id = ?",
                     (before.get("content"), before.get("page_end"), row["node_id"]))
    if action != "rejected":
        conn.execute("UPDATE candidates SET status = 'pending', merged_into = NULL WHERE id = ?",
                     (row["candidate_id"],))
    else:
        conn.execute("UPDATE candidates SET status = 'pending' WHERE id = ?",
                     (row["candidate_id"],))
    conn.execute("UPDATE action_log SET undone = 1 WHERE token = ?", (token,))
    sync_book_counts(conn, row["book_id"])
    conn.commit()
    conn.close()
    return True


def reject_candidate(candidate_id: str) -> dict:
    conn = get_db()
    cur = conn.execute("UPDATE candidates SET status = 'rejected' WHERE id = ? AND status = 'pending'",
                       (candidate_id,))
    if cur.rowcount == 0:
        conn.close()
        return {"ok": False}
    book = conn.execute("SELECT book_id FROM candidates WHERE id = ?", (candidate_id,)).fetchone()
    token = _log_action(conn, book["book_id"], "rejected", candidate_id, None, {})
    conn.commit()
    conn.close()
    return {"ok": True, "undo_token": token}


def merge_candidate(candidate_id: str, node_id: str) -> dict:
    conn = get_db()
    c = conn.execute("SELECT * FROM candidates WHERE id = ? AND status = 'pending'",
                     (candidate_id,)).fetchone()
    n = conn.execute("SELECT id, content, book_id, page_end FROM graph_nodes WHERE id = ?",
                     (node_id,)).fetchone()
    if not c or not n or c["book_id"] != n["book_id"]:
        conn.close()
        return {"ok": False}
    before = {"content": n["content"], "page_end": n["page_end"]}
    conn.execute("UPDATE graph_nodes SET content = ? WHERE id = ?",
                 ((n["content"] or "") + "\n\n" + (c["content"] or ""), node_id))
    conn.execute("UPDATE candidates SET status = 'merged', merged_into = ? WHERE id = ?",
                 (node_id, candidate_id))
    token = _log_action(conn, n["book_id"], "merge", candidate_id, node_id, before)
    sync_book_counts(conn, n["book_id"])
    conn.commit()
    conn.close()
    return {"ok": True, "undo_token": token}
