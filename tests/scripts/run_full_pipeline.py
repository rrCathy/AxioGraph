"""
AxioGraph 全流程测试 — 两本书（中文 + 英文）完整知识图谱
修复版：处理章节碎片化问题
"""
import sys, os, io, json, time, uuid, threading
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r'C:\newproject\AxioGraph\backend')
sys.path.insert(0, '.')

from parser import parse_pdf, chunk_text, detect_language
from extractor import extract_from_text, extract_from_chapters
from graph_store import save_nodes_and_edges, get_graph_for_book
from database import init_db, get_db

# ─── 配置 ──────────────────────────────────────────────
TEST_BOOKS = {
    "galois":  r"C:\newproject\AxioGraph\tests\伽罗瓦理论-章璞.pdf",
}
MIN_CHAPTER_CHARS = 800    # 跳过太短的章节（碎片）
MAX_CHAPTERS = 0           # 0 = 不限制，处理所有合格章节
MAX_WORKERS = 4

# ─── 工具函数 ──────────────────────────────────────────
def print_sep(title: str, char: str = "="):
    print(f"\n{char * 70}")
    print(f"  {title}")
    print(f"{char * 70}")

def print_graph_summary(book_id: str, label: str):
    """打印知识图谱摘要"""
    graph = get_graph_for_book(book_id)
    nodes = graph["elements"]["nodes"]
    edges = graph["elements"]["edges"]

    print(f"\n  ┌─ {label} 知识图谱 ──────────────────────────────")
    print(f"  │ 节点: {len(nodes)} 个    边: {len(edges)} 条")

    type_counts = {}
    for n in nodes:
        t = n["data"]["entity_type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    print(f"  │ 节点类型分布:")
    for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  │   {t:16s} {c:4d}")

    edge_types = {}
    for e in edges:
        t = e["data"]["relation_type"]
        edge_types[t] = edge_types.get(t, 0) + 1

    print(f"  │ 关系类型分布:")
    for t, c in sorted(edge_types.items(), key=lambda x: -x[1]):
        print(f"  │   {t:16s} {c:4d}")

    # 所有节点
    print(f"  │")
    print(f"  │ 全部节点 ({len(nodes)}):")
    name_map = {n["data"]["id"]: n["data"]["name"] for n in nodes}
    for i, n in enumerate(nodes):
        name = n["data"]["name"][:55]
        etype = n["data"]["entity_type"]
        content = n["data"]["content"][:120].replace('\n', ' ')
        print(f"  │ {i+1:2d}. [{etype:12s}] {name}")
        print(f"  │     {content}...")

    # 所有边
    if edges:
        print(f"  │")
        print(f"  │ 全部边 ({len(edges)}):")
        for i, e in enumerate(edges):
            src = name_map.get(e["data"]["source"], "?")[:35]
            tgt = name_map.get(e["data"]["target"], "?")[:35]
            rel = e["data"]["relation_type"]
            desc = e["data"].get("description", "")[:40]
            print(f"  │ {i+1:2d}. {src} --[{rel}]--> {tgt}")
            if desc:
                print(f"  │     └ {desc}")

    print(f"  └{'─' * 50}")

    # 输出 JSON
    safe_label = label.replace(" ", "_").replace("(", "").replace(")", "")
    out_path = rf"C:\newproject\AxioGraph\tests\output_{safe_label}_graph.json"
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)
    print(f"\n  📄 完整图谱 JSON: tests/output_{safe_label}_graph.json")

    # 输出文本
    txt_path = rf"C:\newproject\AxioGraph\tests\output_{safe_label}_nodes.txt"
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(f"{label} 知识图谱\n{'='*60}\n")
        f.write(f"总计: {len(nodes)} 节点, {len(edges)} 边\n\n")
        f.write("=== 节点 ===\n")
        for n in nodes:
            f.write(f"[{n['data']['entity_type']}] {n['data']['name']}\n")
            f.write(f"  chapter: {n['data'].get('chapter', '?')}\n")
            f.write(f"  {n['data']['content'][:500]}\n\n")
        if edges:
            f.write("\n=== 边 ===\n")
            name_map2 = {n["data"]["id"]: n["data"]["name"] for n in nodes}
            for e in edges:
                src = name_map2.get(e["data"]["source"], "?")
                tgt = name_map2.get(e["data"]["target"], "?")
                f.write(f"{src} --[{e['data']['relation_type']}]--> {tgt}\n")
                if e["data"].get("description"):
                    f.write(f"  note: {e['data']['description']}\n")
    print(f"  📄 文本节点列表: tests/output_{safe_label}_nodes.txt")
    return graph


# ─── 主流程 ────────────────────────────────────────────
def main():
    init_db()

    # 清理旧数据
    conn = get_db()
    conn.execute("DELETE FROM graph_edges")
    conn.execute("DELETE FROM graph_nodes")
    conn.execute("DELETE FROM books")
    conn.commit()
    conn.close()
    print("🧹 已清理旧数据\n")

    for lang_key, pdf_path in TEST_BOOKS.items():
        book_label = "伽罗瓦理论-章璞" if lang_key == "galois" else "Serre-LinearRepresentations"
        book_id = str(uuid.uuid4())
        fname = os.path.basename(pdf_path)
        title = fname.replace(".pdf", "")

        print_sep(f"📖 处理: {title}")

        # ─── Step 1: 解析 PDF ───
        t0 = time.time()
        print(f"\n  [Step 1] 解析 PDF...")
        chapters = parse_pdf(pdf_path)

        # 分类章节 — 由于 PDF 解析器对中文书名章节分类不完美，
        # 我们对所有章节按内容长度筛选，并过滤明显的前言/目录
        PREAMBLE_KEYWORDS = [
            'Contents', 'Preface', 'Introduction', 'Notation', 'Acknowledg',
            '前言', '导言', '序言', '目录', '概观', '符号', '致谢', '版权',
            'INTRODUCTION', 'CONTENTS', 'PREFACE',
        ]

        def _is_preamble(title):
            t = title.strip()
            for kw in PREAMBLE_KEYWORDS:
                if t.startswith(kw) or t == kw:
                    return True
            return False

        body = [ch for ch in chapters if not ch.get("is_frontmatter", False)]
        front = [ch for ch in chapters if ch.get("is_frontmatter", False)]

        # 从前言中也挑选有实质内容的章节
        front_substantial = [ch for ch in front
                             if len(ch.get("content", "")) >= MIN_CHAPTER_CHARS
                             and not _is_preamble(ch.get("title", ""))]

        # 正文中筛选足够大的章节
        body_qualified = [ch for ch in body if len(ch.get("content", "")) >= MIN_CHAPTER_CHARS]

        # 合并：正文优先，前言补充
        all_qualified = body_qualified + front_substantial

        print(f"  总章节: {len(chapters)}")
        print(f"    前言/目录: {len(front)}  (其中实质内容章节: {len(front_substantial)})")
        print(f"    正文(全部): {len(body)}  (其中≥{MIN_CHAPTER_CHARS}字符: {len(body_qualified)})")
        print(f"    合计可用: {len(all_qualified)}")

        # 检测语言（从内容检测）
        if all_qualified:
            sample_text = " ".join(ch["content"][:500] for ch in all_qualified[:5])
        else:
            sample_text = " ".join(ch["content"][:500] for ch in chapters[:10])
        lang = detect_language(sample_text)
        print(f"    检测语言: {lang} ({'中文' if lang == 'zh' else '英文'})")

        # 限制处理章节数（0 = 不限制）
        limit = MAX_CHAPTERS if MAX_CHAPTERS > 0 else len(all_qualified)
        active_body = all_qualified[:limit]
        print(f"    实际处理: {len(active_body)} 个章节")
        for ch in active_body:
            title_short = ch.get("title", "?")[:70]
            content_len = len(ch.get("content", ""))
            print(f"      · {title_short}  ({content_len} 字符)")

        t_parse = time.time() - t0
        print(f"  ⏱ 解析耗时: {t_parse:.1f}s")

        if not active_body:
            print(f"\n  ⚠️ 没有合格的章节可以处理，跳过")
            continue

        # ─── Step 2: 分块 + LLM 提取 ───
        print(f"\n  [Step 2] LLM 提取实体与关系 (并行 {MAX_WORKERS} workers)...")
        t1 = time.time()

        # 预览 chunk 数量
        total_chunks_preview = 0
        for ch in active_body:
            total_chunks_preview += len(chunk_text(ch["content"], max_chars=3000))
        print(f"  预计 {total_chunks_preview} 个 chunks 待处理")

        # 注册书籍
        conn = get_db()
        conn.execute(
            "INSERT INTO books (id, title, filename, language, status) VALUES (?, ?, ?, ?, 'extracting')",
            (book_id, title, fname, lang)
        )
        conn.commit()
        conn.close()

        lock = threading.Lock()
        last_report = [0]

        def progress(done, total, nodes, edges):
            with lock:
                pct = int(done / total * 100) if total > 0 else 0
                if pct - last_report[0] >= 5 or done % 3 == 0 or done == total:
                    last_report[0] = pct
                    elapsed = time.time() - t1
                    eta = (elapsed / done * (total - done)) if done > 0 else 0
                    print(f"    [{done:3d}/{total:3d}] {pct:3d}%  |  nodes={nodes:4d}  edges={edges:4d}  |  {elapsed:.0f}s  eta={eta:.0f}s")

        pause_evt = threading.Event()
        pause_evt.set()
        cancel_evt = threading.Event()

        nodes, edges, stats = extract_from_chapters(
            active_body, book_id,
            progress_callback=progress,
            pause_event=pause_evt,
            cancel_event=cancel_evt,
            max_workers=MAX_WORKERS,
        )

        t_extract = time.time() - t1
        print(f"\n  ⏱ 提取耗时: {t_extract:.1f}s")
        print(f"  统计: {stats['total_chunks']} chunks, {stats['failed_chunks']} 失败")
        print(f"  提取: {len(nodes)} 节点, {len(edges)} 边")

        if stats.get('first_error'):
            print(f"  首个错误: {stats['first_error'][:200]}")

        # ─── Step 3: 保存到数据库 ───
        print(f"\n  [Step 3] 保存到图数据库...")
        if nodes:
            save_nodes_and_edges(nodes, edges, book_id)
            conn = get_db()
            conn.execute(
                "UPDATE books SET status='done', node_count=?, edge_count=? WHERE id=?",
                (len(nodes), len(edges), book_id)
            )
            conn.commit()
            conn.close()
            print(f"  ✅ 已保存 {len(nodes)} 节点 + {len(edges)} 边到 SQLite")
        else:
            conn = get_db()
            conn.execute("UPDATE books SET status='done (no math content found)' WHERE id=?", (book_id,))
            conn.commit()
            conn.close()
            print(f"  ⚠️ 未提取到数学实体")

        # ─── Step 4: 输出知识图谱 ───
        if nodes:
            print(f"\n  [Step 4] 知识图谱输出:")
            print_graph_summary(book_id, book_label)
        else:
            print(f"\n  ⚠️ 跳过图谱输出（无数据）")

        total_time = time.time() - t0
        print(f"\n  ⏱ 本书总耗时: {total_time:.1f}s")

    # ─── 最终总结 ───
    print_sep("📊 全流程测试完成")
    conn = get_db()
    rows = conn.execute("SELECT title, language, status, node_count, edge_count FROM books").fetchall()
    conn.close()
    for r in rows:
        print(f"  [{r['language']}] {r['title'][:55]:55s}  status={r['status'][:30]:30s}  nodes={r['node_count']:4d}  edges={r['edge_count']:4d}")

    print(f"\n  📂 输出文件在 tests/ 目录下:")
    import glob as g
    for f in sorted(g.glob(r"C:\newproject\AxioGraph\tests\output_*.json")):
        size_kb = os.path.getsize(f) / 1024
        print(f"     {os.path.basename(f)} ({size_kb:.1f} KB)")
    for f in sorted(g.glob(r"C:\newproject\AxioGraph\tests\output_*.txt")):
        size_kb = os.path.getsize(f) / 1024
        print(f"     {os.path.basename(f)} ({size_kb:.1f} KB)")
    print()


if __name__ == "__main__":
    main()
