import json
import uuid
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from services.llm import get_llm
from parser import detect_language

EXTRACTION_PROMPT_ZH = """你是数学文献分析专家。从以下文本中**完整提取每一个**数学实体及其关系，生成结构化知识图谱。

## 核心要求：

### 1. 全量提取
提取当前文本中出现的**所有**有明确定义、定理陈述或证明的数学实体。不要遗漏任何实体。

### 2. 结构化内容 —— 关键要求
entity.content 必须是一个**结构化对象**，将定理陈述和证明分开：
```
{
  "statement": "定理的完整陈述（原文，保留数学符号，用 $...$ 包裹TeX公式）",
  "proof": "完整证明（保留原文全部论证细节，用 $...$ 包裹TeX公式）"
}
```
如果是定义（DEFINITION），使用：
```
{
  "definition": "概念的完整定义（原文，保留数学符号，用 $...$ 包裹TeX公式）",
  "explanation": "补充说明或性质（如有）"
}
```
如果是例题（EXAMPLE），使用：
```
{
  "problem": "题目描述",
  "solution": "解答或应用"
}
```
每个部分尽量完整保留，不要截断。用 $...$ 包裹所有数学公式（如 $G$、$x^2+1=0$、$\\mathbb{Z}$）。内容不完整的实体不要提取。

### 3. 名称精确 —— 严禁提取裸符号
entity.name 必须是**有意义的完整名称**（如"Frobenius定理""伽罗瓦基本定理""阿廷引理""群作用"），**绝不能**是：
- 单个数学符号：$G$、$H$、$x$、$f$、$\\alpha$
- 函数记号：$g(x)$、$f(x,y)$、$\\phi$
- 纯编号：定理1.2、Lemma 3
- 泛称：群、环、域、定理、引理

如果文本中某实体确实没有名字（如无名引理），用描述性名称（如"关于正规子群的可数性引理"）。

### 4. 关系必标
实体之间有逻辑关系时**必须标注关系**。数学知识是网络状的——不要孤立地列出实体。

### 5. 非正文跳过
如果当前文本是前言、目录、序言、致谢、版权声明等非正文内容，输出空数组 []。

## 实体类型：
- DEFINITION: 数学概念的严格定义
- THEOREM: 被证明的数学命题
- LEMMA: 辅助定理
- COROLLARY: 推论
- PROPOSITION: 命题
- EXAMPLE: 具体例题

## 关系类型与方向（A 是当前提取的实体，B 是关系中引用的实体）：
- DEPENDS_ON: A的证明/定义依赖于B（B是更基础的概念/定理）
- PROVES: A证明了B
- GENERALIZES: A是B的推广（B是A的特例）
- EXAMPLE_OF: A是B的例题/应用实例
- BUILDS_ON: A建立在B的概念框架之上

## 输出格式（严格JSON数组）：
[
  {
    "entity": {
      "type": "THEOREM",
      "name": "拉格朗日定理",
      "content": {
        "statement": "设 $G$ 为有限群，$H$ 为 $G$ 的子群，则 $|H|$ 整除 $|G|$，且 $[G:H]=|G|/|H|$。",
        "proof": "将 $G$ 划分为 $H$ 的左陪集。每个陪集有 $|H|$ 个元素，且陪集两两不交，故 $|G|=|H|\\cdot[G:H]$。"
      }
    },
    "relations": [{"target": "陪集分解", "type": "DEPENDS_ON", "note": "证明用到陪集划分"}]
  }
]

当前章节：{section}
文本：
{text}

只输出JSON数组："""

EXTRACTION_PROMPT_EN = """You are a mathematical literature analyst. Extract **every** mathematical entity with definition or proof content from the text below, producing structured knowledge graph data.

## Core Requirements:

### 1. Exhaustive Extraction
Extract **ALL** entities with explicit definitions, theorem statements, or proofs in the current text. Do not cherry-pick — extract everything.

### 2. Structured Content — CRITICAL
entity.content must be a **structured object** that separates statement from proof:
```
{
  "statement": "Full theorem statement (original text, retain math notation, wrap TeX in $...$)",
  "proof": "Complete proof (preserve all reasoning details from original, wrap TeX in $...$)"
}
```
For definitions (DEFINITION), use:
```
{
  "definition": "Complete definition (original text, retain math notation, wrap TeX in $...$)",
  "explanation": "Supplementary properties or remarks (if any)"
}
```
For examples (EXAMPLE), use:
```
{
  "problem": "Problem statement",
  "solution": "Solution or application"
}
```
Each part should be complete — do not truncate. Wrap ALL math formulas in $...$ (e.g., $G$, $x^2+1=0$, $\\mathbb{Z}$). Skip entities with insufficient content.

### 3. Precise Naming — NO BARE SYMBOLS
entity.name must be a **meaningful full name** (e.g., "Fundamental Theorem of Galois Theory", "Artin's Lemma", "Group Action"). **NEVER extract**:
- Bare math symbols: $G$, $H$, $x$, $f$, $\\alpha$
- Function notation: $g(x)$, $f(x,y)$, $\\phi$
- Bare numbers: Theorem 1.2, Lemma 3
- Generic terms: group, ring, field, theorem, lemma

If an entity truly has no established name, use a descriptive name (e.g., "Lemma on Countability of Normal Subgroups").

### 4. Relations Required
When entities are logically connected (dependency, generalization, proof relationship), you **must** annotate the relation. Mathematics is a web — do not list isolated entities.

### 5. Skip Non-Content
If the current text is preface, table of contents, acknowledgments, copyright, or other non-content, output an empty array [].

## Entity Types:
- DEFINITION: Rigorous definition of a mathematical concept
- THEOREM: A proved mathematical statement
- LEMMA: Auxiliary theorem
- COROLLARY: Corollary
- PROPOSITION: Proposition
- EXAMPLE: Concrete example

## Relation Types and Direction (A = the entity being extracted, B = the target entity):
- DEPENDS_ON: A's proof/definition depends on B (B is more foundational)
- PROVES: A proves B
- GENERALIZES: A generalizes B (B is a special case of A)
- EXAMPLE_OF: A is an example/application of B
- BUILDS_ON: A builds on B's conceptual framework

## Output Format (strict JSON array):
[
  {
    "entity": {
      "type": "THEOREM",
      "name": "Lagrange's Theorem",
      "content": {
        "statement": "Let $G$ be a finite group and $H$ a subgroup. Then $|H|$ divides $|G|$, and $[G:H]=|G|/|H|$.",
        "proof": "Partition $G$ into left cosets of $H$. Each coset has $|H|$ elements and they partition $G$, so $|G|=|H|\\cdot[G:H]$."
      }
    },
    "relations": [{"target": "Coset Decomposition", "type": "DEPENDS_ON", "note": "Proof uses coset partition"}]
  }
]

Current section: {section}
Text:
{text}

Output ONLY the JSON array:"""


_llm_cache: dict = {}
_lock = threading.Lock()


def _get_cached_llm(task: str = "extraction"):
    """Create LLM client once and reuse across chunks."""
    key = f"llm_{task}"
    if key not in _llm_cache:
        _llm_cache[key] = get_llm(task)
    return _llm_cache[key]


def extract_from_text(text: str, section: str = "", llm=None) -> list[dict]:
    if llm is None:
        llm = _get_cached_llm("extraction")
    lang = detect_language(text)
    prompt = EXTRACTION_PROMPT_ZH if lang == "zh" else EXTRACTION_PROMPT_EN
    prompt = prompt.replace("{section}", section or "正文")
    prompt = prompt.replace("{text}", text[:8000])

    messages = [
        {"role": "system", "content": "You are a mathematical knowledge extraction tool. Focus on extracting entities WITH their relationships. Always include relations when entities are connected. Output only valid JSON."},
        {"role": "user", "content": prompt},
    ]

    response = llm.chat(messages, temperature=0.1, max_tokens=16384)

    try:
        match = re.search(r'\[.*\]', response, re.DOTALL)
        if match:
            return json.loads(match.group())
        return json.loads(response)
    except json.JSONDecodeError:
        return []


# Blocklist: generic single-word concepts that should never be nodes
GENERIC_BLOCKLIST = {
    "群", "环", "域", "模", "集", "数", "代数", "代数学", "数学",
    "定理", "引理", "推论", "定义", "公理", "命题", "证明",
    "group", "ring", "field", "set", "algebra", "math", "mathematics",
    "theorem", "lemma", "corollary", "definition", "axiom", "proposition", "proof",
    "结构", "概念", "性质", "关系", "对象", "理论",
    "structure", "concept", "property", "relation", "object", "theory",
}

# Minimum content length required for a node to be accepted
MIN_CONTENT_LEN = 40

# --- Pattern-based rejection for meaningless symbol nodes ---

# Patterns that match bare function/variable notation: g(x), f(x,y), phi, H, G, alpha_1, etc.
_SYMBOL_PATTERNS = [
    re.compile(r'^[a-zA-Z]\\?$'),                          # single letter: x, f, H, G, α (bare)
    re.compile(r'^[a-zA-Z]\\?\s*\([^)]*\)$'),              # f(x), g(y), H(s,t)
    re.compile(r'^\\?[a-zA-Z][a-zA-Z0-9]?\s*\([^)]*\)$'), # f_1(x), G_0(y)
    re.compile(r'^\\?[a-zA-Z]+_\d+$'),                     # f_1, x_0, G_2
    re.compile(r'^\\?[a-zA-Z]{1,2}\'$'),                   # f', G' (derivative notation)
    re.compile(r'^\\[a-zA-Z]+$'),                          # \alpha, \beta, \Gamma (LaTeX bare)
]

def _is_bare_symbol(name: str) -> bool:
    """Check if the name is a bare mathematical symbol/function notation (reject)."""
    stripped = name.strip()
    for pat in _SYMBOL_PATTERNS:
        if pat.match(stripped):
            return True
    return False


def _is_valid_node(name: str, content_input) -> bool:
    """Filter out garbage/generic/symbol nodes. content_input can be str or dict."""
    if not name or len(name.strip()) < 2:
        return False
    name_lower = name.strip().lower()
    if name_lower in GENERIC_BLOCKLIST:
        return False
    if _is_bare_symbol(name):
        return False
    if len(name.strip()) <= 1:
        return False
    return True


def _get_content_len(content) -> int:
    """Get total length of content (str or structured dict)."""
    if isinstance(content, str):
        return len(content)
    if isinstance(content, dict):
        return sum(len(str(v)) for v in content.values())
    return 0


def _is_substantial_node(name: str, content) -> bool:
    """Check if a node has enough content to stand on its own (not a stub)."""
    if not _is_valid_node(name, content):
        return False
    if _get_content_len(content) < MIN_CONTENT_LEN:
        return False
    # Reject stub/generated content placeholders
    if isinstance(content, str):
        stub_markers = ["由「", "由\"", "被「", "引用", "referenced by"]
        for marker in stub_markers:
            if marker in content:
                return False
    return True


def extract_from_chapters(chapters: list[dict], book_id: str,
                          progress_callback=None,
                          pause_event=None, cancel_event=None,
                          max_workers: int = 4) -> tuple[list[dict], list[dict], dict]:
    """Extract knowledge graph from all chapters with parallel LLM calls.
    
    Two-pass approach:
      1. Collect all entities and pending relations from all chunks.
      2. Resolve relations: only create edges where both source and target are substantial nodes.
         NEVER create stub/placeholder nodes for missing targets.
    """
    # --- Shared state (behind lock) ---
    node_names: dict[str, str] = {}        # key -> node_id (for substantial nodes only)
    all_nodes: list[dict] = []
    pending_relations: list[dict] = []     # (source_name, source_type, target_name, rel_type, note, chapter)
    failed_chunks = 0
    first_error = None
    results_lock = threading.Lock()

    from parser import chunk_text
    all_chunks = []
    for ch in chapters:
        chunks = chunk_text(ch["content"], max_chars=3000)
        for chunk in chunks:
            if len(chunk.strip()) >= 100:
                all_chunks.append((ch, chunk))

    total_chunks = len(all_chunks)
    llm = _get_cached_llm("extraction")

    def _process_chunk(idx_ch_section):
        idx, ch, chunk_text_val = idx_ch_section
        if cancel_event and cancel_event.is_set():
            return None, None, True
        if pause_event:
            pause_event.wait()
        try:
            results = extract_from_text(chunk_text_val, section=ch.get("title", "")[:100], llm=llm)
            return results, idx, False
        except Exception as e:
            return str(e), idx, False

    # ---- Pass 1: collect all entities and pending relations ----
    completed = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_process_chunk, (i, ch, chunk)): i
            for i, (ch, chunk) in enumerate(all_chunks)
        }

        for future in as_completed(futures):
            if cancel_event and cancel_event.is_set():
                for f in futures:
                    f.cancel()
                break

            results, idx, cancelled = future.result()
            if cancelled:
                continue

            completed += 1

            if isinstance(results, str):
                failed_chunks += 1
                if first_error is None:
                    first_error = results
            elif results:
                chapter_title = all_chunks[idx][0].get("title", "")[:100]
                with results_lock:
                    for item in results:
                        entity = item.get("entity", {})
                        name = entity.get("name", "").strip()
                        etype = entity.get("type", "CONCEPT").upper()
                        content = entity.get("content", "")

                        # Normalize content: dict → JSON string for DB storage; str → keep as-is
                        if isinstance(content, dict):
                            content_str = json.dumps(content, ensure_ascii=False)
                        elif isinstance(content, str):
                            content_str = content.strip()
                        else:
                            content_str = str(content)

                        if not _is_substantial_node(name, content_str if isinstance(content, dict) else content_str):
                            continue

                        node_key = f"{name}|{etype}"
                        if node_key not in node_names:
                            node_id = str(uuid.uuid4())
                            node_names[node_key] = node_id
                            all_nodes.append({
                                "id": node_id, "book_id": book_id,
                                "entity_type": etype, "name": name,
                                "content": content_str,
                                "chapter": chapter_title,
                            })

                        for rel in item.get("relations", []):
                            target = rel.get("target", "").strip()
                            rtype = rel.get("type", "RELATED_TO").upper()
                            note = rel.get("note", "")
                            if not target or len(target.strip()) < 2:
                                continue
                            pending_relations.append({
                                "source_name": name,
                                "source_type": etype,
                                "target_name": target,
                                "relation_type": rtype,
                                "note": note,
                                "chapter": chapter_title,
                            })

            if progress_callback:
                progress_callback(completed, total_chunks, len(all_nodes), 0)

    # ---- Pass 2: resolve pending relations (with stub node fallback) ----
    all_edges: list[dict] = []
    resolved_count = 0
    skipped_count = 0
    stub_count = 0

    for rel in pending_relations:
        source_key = f"{rel['source_name']}|{rel['source_type']}"
        if source_key not in node_names:
            continue

        target_name = rel["target_name"]
        target_key = f"{target_name}|{rel['source_type']}"

        if target_key not in node_names:
            # Try any type match (the target might be extracted as a different type)
            found = False
            for existing_key in node_names:
                existing_name = existing_key.rsplit("|", 1)[0]
                if existing_name == target_name:
                    target_key = existing_key
                    found = True
                    break
            if not found:
                # Pass 3-style fallback: create stub CONCEPT node for referenced target
                stub_key = f"{target_name}|CONCEPT"
                if _is_valid_node(target_name, "") and len(target_name.strip()) >= 3:
                    if stub_key not in node_names:
                        stub_id = str(uuid.uuid4())
                        node_names[stub_key] = stub_id
                        all_nodes.append({
                            "id": stub_id, "book_id": book_id,
                            "entity_type": "CONCEPT", "name": f"[ref] {target_name}",
                            "content": "",
                            "chapter": rel.get("chapter", ""),
                        })
                        stub_count += 1
                    # Now use the stub node as target
                    target_key = stub_key
                else:
                    skipped_count += 1
                    continue

        resolved_count += 1
        all_edges.append({
            "source_id": node_names[source_key],
            "target_id": node_names[target_key],
            "relation_type": rel["relation_type"],
            "description": rel["note"],
            "book_id": book_id,
        })

    # Update progress with final counts
    if progress_callback:
        progress_callback(completed, total_chunks, len(all_nodes), len(all_edges))

    return all_nodes, all_edges, {
        "total_chunks": total_chunks,
        "failed_chunks": failed_chunks,
        "node_count": len(all_nodes),
        "edge_count": len(all_edges),
        "first_error": first_error,
        "pending_relations": len(pending_relations),
        "resolved_edges": resolved_count,
        "skipped_edges": skipped_count,
        "stub_nodes_created": stub_count,
    }
