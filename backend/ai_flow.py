"""AI auto-flow: read-page extraction → human ✓/✗ review → per-item rework.

Design rules (user-approved):
- The reader clicks a manual "已读" button per page (back-and-forth reading
  makes automatic flip triggers wrong).
- AI writes nodes/edges with review_status='ai_pending' — they are NEVER
  treated as confirmed until a human ticks them.
- A ✗ reworks just that one item (with the reader's note). Three consecutive
  ✗ on the same item abandon it and delete it.
- A ✗'d item is deleted directly (no graveyard).

Field vocabulary matches the human promote dialog (PromoteDialog):
16 entity types, 5 relation types, name/content/quote/page span.
"""
from __future__ import annotations

import json
import re
import uuid

from database import get_db

MAX_ATTEMPTS = 3

VALID_ENTITY_TYPES = {
    "DEFINITION", "THEOREM", "LEMMA", "PROPOSITION", "COROLLARY",
    "AXIOM", "PROOF", "EXAMPLE", "REMARK", "CONJECTURE", "CLAIM",
    "FACT", "ASSUMPTION", "PRINCIPLE", "NOTATION", "CONCEPT",
}
VALID_RELATION_TYPES = {
    "DEPENDS_ON", "GENERALIZES", "PROVES", "BUILDS_ON", "EXAMPLE_OF",
}

# ── Prompt 1: page extraction (mirrors the human promote fields) ────────────

AI_READ_PROMPT = """你是数学教材分析助手。下面是从 PDF 第 {start}-{end} 页按版面重建的结构化文本，每段以 [pN] 标记页码；`#` 标题（层级用 # 个数）、[P] 正文、[FORMULA] 独立公式行。
示意图内标注已被排除，不会出现在输入里，不要凭空补回。

任务：像读者手动「提升」节点一样，把本页值得入知识图谱的数学条目提取出来，直接写入图谱，等读者打勾/打叉。原文可能有识别错误，宁可少提也不要编造。

每个条目对应一个图谱节点，字段与人工提升一致：
1. type 只能取：DEFINITION, THEOREM, LEMMA, PROPOSITION, COROLLARY, AXIOM, EXAMPLE, REMARK, CONJECTURE, CLAIM, FACT, ASSUMPTION, PRINCIPLE, NOTATION, CONCEPT, PROOF
2. name：编号 + 实质主题名的完整名称。好的例子：「定义 4.1.1 半群」「命题 4.1.13 子群的陪集分解与 Lagrange 定理」「引理 4.1.12 双陪集相等条件」。
   禁止：只有编号没有主题（如「定理 4.1.2」「引理 4.1.12」「例 4.1.4」——读者看到这样的名字不知道内容是什么）；
   禁止裸符号 $G$、$f(x)$、泛称"群""定理"。
   原书编号旁若有括号题名务必使用；没有题名就从内容概括 2-8 字主题接在编号后。
3. content：条目完整陈述——定义的条件、定理的结论；数学公式用 $...$ 包裹。条目跨页未完时照录本页部分并标 "continues": true。
4. quote：原文最有代表性的句子（≤200 字），必须真实出现，供读者核对。
5. page_start / page_end：条目正文所在页码。
6. **证明必须单独成节点**：定理/命题/引理/推论若带证明，把证明提取为独立的 type=PROOF 节点——name 写「（被证明条目名）的证明」（如"命题 4.1.13 的证明"），content 抄证明全文（推导、公式、中间步骤都要），并用 relations 的 PROVES 指向被证明的定理节点。只有证明短到一两句话时才可并入定理的 content 末尾、不单独成节点。页面上出现独立「证明」段落而你漏掉它，是最严重的错误。
7. relations：条目与其他节点的关系，只用 5 种：
   DEPENDS_ON（依赖于）| GENERALIZES（推广）| PROVES（证明，从 PROOF 节点指向被证明的定理）| BUILDS_ON（基于）| EXAMPLE_OF（示例）
   target 必须逐字复制「已有节点」清单里的完整名称，或本批其他条目的完整 name——禁止自造简称。
   判断方法：逐条自问「理解或使用这个条目，必须先掌握清单里的哪些概念？」——它们就是 DEPENDS_ON / BUILDS_ON 的候选；「本条目是某概念的具体例子」就是 EXAMPLE_OF。
   数学条目极少孤立：多数定义/定理与已有节点存在 1-3 条真实关系，逐条给出。
   **只连直接关系，禁止传递性推理**：若 A 基于 B、B 基于 C，绝不要再给 A 基于 C——传递的间接关系会让图谱变成蛛网。整页确实与前后文完全无关时才输出空数组。

已有节点（target 可指向它们）：
{confirmed_nodes}

规则：
- 只提取内容完整、有独立入图价值的条目；目录、页眉页脚、习题答案等输出 []。
- [FORMULA] 块由系统单独处理，不要输出公式节点；可在 relations 里引用其概念名。
- 标题行（#）用来判断所属章节，本身不作为实体。
- 本页最多 10 条，优先定义、定理及其证明。
- 只输出严格 JSON 数组，不要任何解释文字：
[
  {{
    "entity": {{"type": "THEOREM", "name": "...", "content": "...",
               "quote": "...", "page_start": 21, "page_end": 21,
               "continues": false}},
    "relations": [{{"target": "...", "type": "DEPENDS_ON", "note": "..."}}]
  }}
]

页码范围：{start}-{end}
原文：
{text}
"""

# ── Prompt 2: node rework (one rejected item at a time) ─────────────────────

REWORK_NODE_PROMPT = """你是数学教材分析助手。字段定义与提取任务一致：
type ∈ DEFINITION, THEOREM, LEMMA, PROPOSITION, COROLLARY, AXIOM, EXAMPLE, REMARK, CONJECTURE, CLAIM, FACT, ASSUMPTION, PRINCIPLE, NOTATION, CONCEPT, PROOF；
name 有意义短名称（可带原书编号）；content 完整陈述（公式用 $...$）；
quote 原文代表句（≤200 字，必须真实出现）；relations 只用
DEPENDS_ON|GENERALIZES|PROVES|BUILDS_ON|EXAMPLE_OF。
注意：定理/命题/引理若带证明，证明单独成 type=PROOF 的节点并用 PROVES 指向被证明条目。
name 必须是编号+主题（如「引理 4.1.12 双陪集相等条件」），禁止只有编号。

读者在点评上一版入图结果时，对以下条目打了叉：
- [{type}] {name}（p{page}）
  原 content 摘要：{content_digest}
  读者评语：{note}

请对照第 {start}-{end} 页原文修正后重新给出该条目：可以改 name / content / quote、换 type，也可以判定此条不该提取——输出 [] 表示放弃。
只输出修正后的条目（0 或 1 项），JSON 数组，格式：
[
  {{
    "entity": {{"type": "...", "name": "...", "content": "...",
               "quote": "...", "page_start": {page}, "page_end": {page},
               "continues": false}},
    "relations": []
  }}
]
不要输出其他条目，不要任何解释文字。

原文：
{text}
"""

# ── Prompt 3: edge rework ───────────────────────────────────────────────────

REWORK_EDGE_PROMPT = """你是数学教材分析助手。关系只用 5 种：
DEPENDS_ON（依赖于）| GENERALIZES（推广）| PROVES（证明）| BUILDS_ON（基于）| EXAMPLE_OF（示例）。

读者在点评时打叉了这条关系：
  [{source_name}] --{relation}--> [{target_name}]（原 note：{note}）
  读者评语：{user_note}

请对照第 {start}-{end} 页原文重新判断这两个节点的关系：给出正确的关系（5 种词表，可换类型或调转方向），或判定两节点无关系输出 []。
只输出 JSON 数组：
[{{"source": "...", "target": "...", "type": "...", "note": "..."}}]
不要任何解释文字。

两个节点的内容供参考：
[{source_name}] {source_content}
[{target_name}] {target_content}

原文：
{text}
"""


# ── JSON parsing (same tolerant approach as page_extractor) ─────────────────

def _parse_array(response: str) -> list[dict]:
    if not response or not response.strip():
        return []
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "",
                  response.strip(), flags=re.I | re.M).strip()
    candidates: list[str] = []
    m = re.search(r"\[.*\]", text, re.S)
    if m:
        candidates.append(m.group())
    candidates.append(text)
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, list):
                return [x for x in data if isinstance(x, dict)]
        except json.JSONDecodeError:
            continue
    try:
        import json_repair
        data = json_repair.loads(text)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    except Exception:
        pass
    return []


def _llm(messages: list[dict]) -> list[dict]:
    """One extraction call with a bounded retry: the free aggregator 429s
    under burst load, and a user-facing "已读" click must survive that."""
    from services.llm import get_llm
    import time as _time
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            raw = get_llm("extraction").chat(messages, temperature=0.1, max_tokens=4096)
            return _parse_array(raw)
        except Exception as e:
            last_err = e
            if attempt == 0:
                _time.sleep(8)  # rate-limit window; one bounded retry
    raise last_err  # type: ignore[misc]


# ── Read page → ai_pending items ────────────────────────────────────────────

def _confirmed_names(book_id: str) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        """SELECT id, name, entity_type FROM graph_nodes
           WHERE book_id = ? AND review_status = 'confirmed' AND deleted = 0
           ORDER BY page_start LIMIT 120""",
        (book_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _norm_type(t: str) -> str:
    t = (t or "CONCEPT").strip().upper()
    return t if t in VALID_ENTITY_TYPES else "CONCEPT"


_BARE_NAME_RE = re.compile(
    r"""^\s*(?:定理|引理|命题|定义|例|推论|公理|注记|习题|猜想|断言|事实|
        假设|原理|记号|问题|Theorem|Lemma|Proposition|Definition|Example|
        Corollary|Remark|Claim|Fact|Exercise|Conjecture|Principle|Notation)?
        \s*[\dA-Za-z]?[\d\.．\-]*\s*$""", re.I | re.X)


def _materialise_name(name: str, content: str) -> str:
    """Bare numbered names ('引理 4.1.12') tell the reader nothing. The
    auto-flow has no human rename step before the item goes live, so graft
    a short topic from the content's first clause onto the number."""
    name = (name or "").strip()
    if not _BARE_NAME_RE.match(name):
        return name
    topic_src = (content or "").strip()
    # strip display math so the topic is prose, not formula fragments
    topic_src = re.sub(r"\$\$?[^$]*\$\$?", " ", topic_src)
    topic_src = re.sub(r"\s+", " ", topic_src)
    if not topic_src:
        return name
    # First ~16 chars, cut back to the last clause boundary when the
    # leading clause is long enough — Chinese math prose commas arrive
    # early ('设H, K 为…'), and a 2-char fragment is no topic at all.
    window = topic_src[:16]
    cut = None
    for m in re.finditer(r"[，,；;。：:（(]", window):
        cut = m.start()
    if cut is not None and cut >= 4:
        window = window[:cut]
    # trailing connective after the last comma reads broken ('…的子群, 则')
    clause = re.sub(r"[，,；;。：:（(]\s*(则|那么|于是|有|若|如果)?\s*$", "", window).strip()
    if len(clause) < 2:
        return name
    return f"{name} {clause}"


def _num_key(name: str) -> str | None:
    """The numbered identity of an item ('注记 4.1.15 …' → '4.1.15').

    LLM output wording varies between runs, so exact-name dedup misses
    repeats; the book-unique number+type pair is the stable key.
    """
    m = re.search(r"\d+(?:\.\d+)+", name or "")
    return m.group(0) if m else None


def read_page(book_id: str, page_no: int) -> dict:
    """Extract one page's entities straight into ai_pending state."""
    import page_service as ps
    text = ps.window_text(book_id, page_no, page_no)
    if not text.strip():
        return {"items": 0, "reason": "no text on this page"}

    names = _confirmed_names(book_id)
    name_lines = "\n".join(f'- {n["name"]} [{n["entity_type"]}]' for n in names) or "（无）"
    prompt = (AI_READ_PROMPT
              .replace("{start}", str(page_no)).replace("{end}", str(page_no))
              .replace("{confirmed_nodes}", name_lines)
              .replace("{text}", text[:12000]))
    items = _llm([
        {"role": "system",
         "content": "You extract mathematical entities as strict JSON. "
                    "Never invent content. Output only a JSON array."},
        {"role": "user", "content": prompt},
    ])

    conn = get_db()
    created_nodes = 0
    created_edges = 0
    # name → id for this batch, so relations between batch items resolve.
    batch_ids: dict[str, str] = {}
    known = {n["name"] for n in names}

    for item in items:
        ent = item.get("entity") or {}
        name = str(ent.get("name", "")).strip()
        if not name or len(name) < 2:
            continue
        etype = _norm_type(str(ent.get("type", "")))
        content = str(ent.get("content", "")).strip()
        if isinstance(ent.get("content"), (dict, list)):
            content = json.dumps(ent["content"], ensure_ascii=False)
        name = _materialise_name(name, content)
        quote = str(ent.get("quote", ""))[:400]
        p_start = int(ent.get("page_start") or page_no)
        p_end = int(ent.get("page_end") or p_start)

        # Dedup against LIVE nodes. LLM wording varies between runs
        # ('注记 4.1.15' vs '注记 4.1.15 若N…'), so match on (type, number)
        # first — the book-unique identity — then on exact name. Confirmed
        # duplicates are skipped; ai_pending ones are updated in place so
        # repeated "已读" clicks never pile up copies. Recycled duplicates
        # don't block a fresh extract (the reader deleted them on purpose).
        nk = _num_key(name)
        same_type = conn.execute(
            """SELECT id, review_status, name FROM graph_nodes
               WHERE book_id = ? AND entity_type = ? AND deleted = 0""",
            (book_id, etype),
        ).fetchall()
        existing = None
        for r in same_type:
            if r["name"] == name or (nk and _num_key(r["name"]) == nk):
                existing = r
                break
        if existing:
            if existing["review_status"] == "confirmed":
                # Reader already owns this item — but relations it takes part
                # in may still be NEW, so keep it resolvable as an edge source.
                batch_ids[name] = existing["id"]
                continue
            conn.execute(
                """UPDATE graph_nodes SET name = ?, content = ?, source_quote = ?,
                       page_start = ?, page_end = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (name, content, quote, p_start, p_end, existing["id"]),
            )
            batch_ids[name] = existing["id"]
            continue

        node_id = str(uuid.uuid4())
        batch_ids[name] = node_id
        conn.execute(
            """INSERT INTO graph_nodes
               (id, book_id, entity_type, name, content, chapter,
                page_start, page_end, review_status, source_quote, created_by, ai_attempts)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ai_pending', ?, 'ai', 0)""",
            (node_id, book_id, etype, name, content,
             f"p{p_start}-{p_end}", p_start, p_end, quote),
        )
        created_nodes += 1

    # Second pass: relations, after every batch name has an id.
    def resolve(target: str) -> str | None:
        """Resolve a relation target to a node id. LLM wording varies ('子群'
        vs '定义 4.1.7 子群和正规子群'), so after exact matches fall back to
        containment: the target must appear inside a node name (prefix bias)
        and the closest name wins when several contain it."""
        t = target.strip()
        if not t:
            return None
        if t in batch_ids:
            return batch_ids[t]
        cands = [n for n in names if t in n["name"] or n["name"] in t]
        if not cands:
            return None
        if len(cands) == 1:
            return cands[0]["id"]
        # several contain it → prefix match first, then the tightest name
        prefixed = [n for n in cands if n["name"].startswith(t)]
        if prefixed:
            cands = prefixed
        return min(cands, key=lambda n: abs(len(n["name"]) - len(t)))["id"]

    for item in items:
        ent = item.get("entity") or {}
        src_name = str(ent.get("name", "")).strip()
        src_id = batch_ids.get(src_name)
        if not src_id:
            continue
        for rel in item.get("relations") or []:
            tgt_name = str(rel.get("target", "")).strip()
            rel_type = str(rel.get("type", "")).strip().upper()
            if not tgt_name or rel_type not in VALID_RELATION_TYPES:
                continue
            tgt_id = resolve(tgt_name)
            if not tgt_id or tgt_id == src_id:
                continue
            dup = conn.execute(
                """SELECT id FROM graph_edges
                   WHERE source_id = ? AND target_id = ? AND relation_type = ?
                     AND book_id = ? AND deleted = 0""",
                (src_id, tgt_id, rel_type, book_id),
            ).fetchone()
            if dup:
                continue
            conn.execute(
                """INSERT INTO graph_edges
                   (source_id, target_id, relation_type, description, book_id,
                    review_status, ai_attempts)
                   VALUES (?, ?, ?, ?, ?, 'ai_pending', 0)""",
                (src_id, tgt_id, rel_type,
                 str(rel.get("note", ""))[:300], book_id),
            )
            created_edges += 1

    conn.execute(
        """INSERT INTO ai_jobs (id, book_id, page_no, status, items_created)
           VALUES (?, ?, ?, 'done', ?)""",
        (str(uuid.uuid4()), book_id, page_no, created_nodes),
    )
    from graph_store import sync_book_counts
    sync_book_counts(conn, book_id)
    conn.commit()
    conn.close()
    return {"items": created_nodes, "edges": created_edges, "page": page_no}


# ── Review: ✓ confirm / ✗ rework-or-drop ────────────────────────────────────

def _node_row(node_id: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM graph_nodes WHERE id = ?", (node_id,)).fetchone()
    conn.close()
    return row


def review_node(node_id: str, accept: bool, note: str = "",
                edits: dict | None = None) -> dict:
    """accept=True → confirmed (with optional human edits first).
    accept=False → one rework attempt; 3rd consecutive ✗ deletes the node."""
    row = _node_row(node_id)
    if not row:
        return {"ok": False, "error": "node not found"}
    if row["review_status"] == "confirmed":
        return {"ok": False, "error": "already confirmed"}

    conn = get_db()
    if accept:
        name = (edits or {}).get("name") or row["name"]
        content = (edits or {}).get("content") or row["content"]
        etype = _norm_type((edits or {}).get("entity_type") or row["entity_type"])
        conn.execute(
            """UPDATE graph_nodes
               SET name = ?, content = ?, entity_type = ?, review_status = 'confirmed',
                   updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (name, content, etype, node_id),
        )
        conn.commit()
        conn.close()
        return {"ok": True, "action": "confirmed", "node_id": node_id}

    attempts = (row["ai_attempts"] or 0) + 1
    if attempts >= MAX_ATTEMPTS:
        conn.execute("DELETE FROM graph_edges WHERE source_id = ? OR target_id = ?",
                     (node_id, node_id))
        conn.execute("DELETE FROM graph_nodes WHERE id = ?", (node_id,))
        conn.execute("INSERT INTO ai_jobs (id, book_id, page_no, status, items_created, error)"
                     " VALUES (?, ?, ?, 'dropped', 0, ?)",
                     (str(uuid.uuid4()), row["book_id"], row["page_start"] or 0,
                      f'3 strikes: {row["name"]}'))
        conn.commit()
        conn.close()
        return {"ok": True, "action": "dropped", "node_id": node_id}

    conn.execute("UPDATE graph_nodes SET ai_attempts = ? WHERE id = ?",
                 (attempts, node_id))
    conn.commit()
    conn.close()

    # Rework this one item against its page text. A rate-limited model must
    # not fail the review action — the strike already counts; rework is best
    # effort and degrades to rework_empty.
    import page_service as ps
    page = row["page_start"] or 1
    text = ps.window_text(row["book_id"], page, row["page_end"] or page)
    digest = (row["content"] or "")[:300]
    prompt = (REWORK_NODE_PROMPT
              .replace("{type}", row["entity_type"] or "")
              .replace("{name}", row["name"] or "")
              .replace("{page}", str(page))
              .replace("{content_digest}", digest)
              .replace("{note}", (note.strip() or "（未填写）")[:300])
              .replace("{start}", str(page))
              .replace("{end}", str(row["page_end"] or page))
              .replace("{text}", text[:10000]))
    try:
        out = _llm([
            {"role": "system", "content": "You revise one mathematical entity. Strict JSON only."},
            {"role": "user", "content": prompt},
        ])
    except Exception:
        out = []
    if not out:
        # Model gave up → treat as drop for this attempt (kept for one more strike).
        return {"ok": True, "action": "rework_empty", "node_id": node_id,
                "attempts": attempts}

    ent = (out[0].get("entity") or {}) if isinstance(out[0], dict) else {}
    if not ent:
        return {"ok": True, "action": "rework_empty", "node_id": node_id,
                "attempts": attempts}
    content = ent.get("content", "")
    if isinstance(content, (dict, list)):
        content = json.dumps(content, ensure_ascii=False)
    conn = get_db()
    new_name = _materialise_name(
        str(ent.get("name", row["name"])).strip() or row["name"],
        str(content).strip() or row["content"] or "")
    conn.execute(
        """UPDATE graph_nodes
           SET entity_type = ?, name = ?, content = ?, source_quote = ?,
               updated_at = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (_norm_type(str(ent.get("type", row["entity_type"]))),
         new_name,
         str(content).strip() or row["content"],
         str(ent.get("quote", row["source_quote"] or ""))[:400],
         node_id),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "action": "reworked", "node_id": node_id, "attempts": attempts}


def review_edge(edge_id: int, accept: bool, note: str = "") -> dict:
    conn = get_db()
    row = conn.execute("SELECT * FROM graph_edges WHERE id = ?", (edge_id,)).fetchone()
    if not row:
        conn.close()
        return {"ok": False, "error": "edge not found"}
    if accept:
        conn.execute(
            "UPDATE graph_edges SET review_status = 'confirmed' WHERE id = ?",
            (edge_id,))
        conn.commit()
        conn.close()
        return {"ok": True, "action": "confirmed", "edge_id": edge_id}

    attempts = (row["ai_attempts"] or 0) + 1
    if attempts >= MAX_ATTEMPTS:
        conn.execute("DELETE FROM graph_edges WHERE id = ?", (edge_id,))
        conn.commit()
        conn.close()
        return {"ok": True, "action": "dropped", "edge_id": edge_id}
    conn.execute("UPDATE graph_edges SET ai_attempts = ? WHERE id = ?",
                 (attempts, edge_id))
    conn.commit()
    conn.close()

    # Rework this one relation.
    conn = get_db()
    src = conn.execute("SELECT * FROM graph_nodes WHERE id = ?", (row["source_id"],)).fetchone()
    tgt = conn.execute("SELECT * FROM graph_nodes WHERE id = ?", (row["target_id"],)).fetchone()
    conn.close()
    if not src or not tgt:
        return {"ok": True, "action": "dropped", "edge_id": edge_id}

    import page_service as ps
    book_id = row["book_id"] or src["book_id"]
    page = src["page_start"] or 1
    text = ps.window_text(book_id, page, src["page_end"] or page)
    prompt = (REWORK_EDGE_PROMPT
              .replace("{source_name}", src["name"] or "")
              .replace("{target_name}", tgt["name"] or "")
              .replace("{relation}", row["relation_type"] or "")
              .replace("{note}", (row["description"] or "")[:200])
              .replace("{user_note}", (note.strip() or "（未填写）")[:300])
              .replace("{start}", str(page))
              .replace("{end}", str(src["page_end"] or page))
              .replace("{source_content}", (src["content"] or "")[:400])
              .replace("{target_content}", (tgt["content"] or "")[:400])
              .replace("{text}", text[:10000]))
    try:
        out = _llm([
            {"role": "system", "content": "You revise one relation. Strict JSON only."},
            {"role": "user", "content": prompt},
        ])
    except Exception:
        out = []
    if not out or not isinstance(out[0], dict):
        return {"ok": True, "action": "rework_empty", "edge_id": edge_id,
                "attempts": attempts}

    rel = out[0]
    rel_type = str(rel.get("type", "")).strip().upper()
    if rel_type not in VALID_RELATION_TYPES:
        return {"ok": True, "action": "rework_empty", "edge_id": edge_id,
                "attempts": attempts}
    # Direction flip: swap endpoints when the model reverses the pair.
    s_name, t_name = str(rel.get("source", "")), str(rel.get("target", ""))
    sid, tid = row["source_id"], row["target_id"]
    if s_name == tgt["name"] and t_name == src["name"]:
        sid, tid = tid, sid
    conn = get_db()
    conn.execute(
        """UPDATE graph_edges
           SET source_id = ?, target_id = ?, relation_type = ?, description = ?
           WHERE id = ?""",
        (sid, tid, rel_type, str(rel.get("note", ""))[:300], edge_id),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "action": "reworked", "edge_id": edge_id, "attempts": attempts}


# ── Review queue listing ────────────────────────────────────────────────────

def list_pending(book_id: str) -> dict:
    conn = get_db()
    nodes = conn.execute(
        """SELECT id, entity_type, name, content, source_quote, page_start,
                  page_end, ai_attempts
           FROM graph_nodes
           WHERE book_id = ? AND review_status = 'ai_pending' AND deleted = 0
           ORDER BY page_start, name""",
        (book_id,),
    ).fetchall()
    edges = conn.execute(
        """SELECT e.id, e.source_id, e.target_id, e.relation_type, e.description,
                  e.ai_attempts, s.name AS source_name, t.name AS target_name
           FROM graph_edges e
           JOIN graph_nodes s ON s.id = e.source_id
           JOIN graph_nodes t ON t.id = e.target_id
           WHERE e.book_id = ? AND e.review_status = 'ai_pending'
             AND e.deleted = 0 AND s.deleted = 0 AND t.deleted = 0
           ORDER BY e.id""",
        (book_id,),
    ).fetchall()
    conn.close()
    return {"nodes": [dict(r) for r in nodes], "edges": [dict(r) for r in edges]}


def list_jobs(book_id: str, limit: int = 20) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        """SELECT id, page_no, status, items_created, error, created_at
           FROM ai_jobs WHERE book_id = ? ORDER BY created_at DESC LIMIT ?""",
        (book_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
