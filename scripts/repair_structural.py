"""
Knowledge Graph Repair Script
Fixes: duplicates, circular dependencies, PROVES directions, OCR artifacts
"""
import sqlite3
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DB = r'C:\newproject\AxioGraph\data\axiograph.db'

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

changes = []  # Track all changes for reporting

def log(change_type, detail):
    changes.append(f"  [{change_type}] {detail}")
    print(f"  [{change_type}] {detail}")

# ============================================================
# PART 1: MERGE DUPLICATE NODES
# ============================================================
print("\n=== PART 1: MERGE DUPLICATES ===")

# Duplicate pair 1: 阿贝尔-鲁菲尼定理 (different dash characters)
dup1_keep = 'd6d62084-ecbe-4c26-9e9c-9692db30dd9a'  # 阿贝尔－鲁菲尼定理 (full-width dash)
dup1_del  = '93999daf-c501-462d-9629-c9470b60661d'   # 阿贝尔‑鲁菲尼定理 (narrow dash)

# Check edges on the node-to-delete
edges_del = conn.execute(
    'SELECT source_id, target_id, relation_type FROM graph_edges WHERE source_id = ? OR target_id = ?',
    (dup1_del, dup1_del)
).fetchall()
print(f"  Node {dup1_del} has {len(edges_del)} edges")

# Reassign edges from dup1_del to dup1_keep
for e in edges_del:
    new_source = dup1_keep if e['source_id'] == dup1_del else e['source_id']
    new_target = dup1_keep if e['target_id'] == dup1_del else e['target_id']
    if new_source != new_target:  # Avoid self-loops
        # Check if edge already exists
        existing = conn.execute(
            'SELECT id FROM graph_edges WHERE source_id = ? AND target_id = ? AND relation_type = ?',
            (new_source, new_target, e['relation_type'])
        ).fetchone()
        if not existing:
            conn.execute(
                'INSERT INTO graph_edges (source_id, target_id, relation_type, description, book_id) VALUES (?, ?, ?, ?, ?)',
                (new_source, new_target, e['relation_type'], '',
                 '401353c5-f45b-4008-b594-e2aa3261013a')
            )
            log("MERGE", f"Reassigned edge: {e['source_id'][:8]} -> {e['target_id'][:8]} ({e['relation_type']}) to keep node")

# Delete the duplicate node (cascade will remove its edges)
conn.execute('DELETE FROM graph_nodes WHERE id = ?', (dup1_del,))
log("MERGE", f"Deleted duplicate: 阿贝尔‑鲁菲尼定理 (narrow dash) -> merged into full-width dash version")

# Duplicate pair 2: 解析开拓 vs 解析开拓（或全纯开拓）
dup2_keep = '79dcda10-dfaf-4a23-9deb-8d4bdcb87e42'   # 解析开拓 (simpler name)
dup2_del  = '21d61101-9c42-45a3-be68-30110f03d9ac'   # 解析开拓（或全纯开拓）

edges_del2 = conn.execute(
    'SELECT source_id, target_id, relation_type FROM graph_edges WHERE source_id = ? OR target_id = ?',
    (dup2_del, dup2_del)
).fetchall()
print(f"  Node {dup2_del} has {len(edges_del2)} edges")

for e in edges_del2:
    new_source = dup2_keep if e['source_id'] == dup2_del else e['source_id']
    new_target = dup2_keep if e['target_id'] == dup2_del else e['target_id']
    if new_source != new_target:
        existing = conn.execute(
            'SELECT id FROM graph_edges WHERE source_id = ? AND target_id = ? AND relation_type = ?',
            (new_source, new_target, e['relation_type'])
        ).fetchone()
        if not existing:
            conn.execute(
                'INSERT INTO graph_edges (source_id, target_id, relation_type, description, book_id) VALUES (?, ?, ?, ?, ?)',
                (new_source, new_target, e['relation_type'], '',
                 'a0eae8c3-916d-4ca7-a36f-a0bd38cd6617')
            )
            log("MERGE", f"Reassigned edge: {e['source_id'][:8]} -> {e['target_id'][:8]} ({e['relation_type']}) to keep node")

conn.execute('DELETE FROM graph_nodes WHERE id = ?', (dup2_del,))
log("MERGE", f"Deleted duplicate: 解析开拓（或全纯开拓） -> merged into 解析开拓")

# Also update the keep node name to include the synonym
conn.execute('UPDATE graph_nodes SET name = ? WHERE id = ?',
             ('解析开拓（全纯开拓）', dup2_keep))

# ============================================================
# PART 2: FIX CIRCULAR DEPENDENCIES
# ============================================================
print("\n=== PART 2: FIX CIRCULAR DEPENDENCIES ===")

# For each cycle, remove the weaker/incorrect edge
cycles_to_fix = [
    # (edge_to_delete_id, reason)
    # Cycle 1: 拉格朗日预解式 DEPENDS_ON 伽罗瓦基本定理 <-> 伽罗瓦基本定理 PROVES 拉格朗日预解式
    # Remove DEPENDS_ON(351) - 拉格朗日预解式 is NOT dependent on the fundamental theorem (it's a technique)
    (351, "拉格朗日预解式 -/-> 伽罗瓦基本定理 (预解式是独立技巧)"),

    # Cycle 2: 伽罗瓦基本定理 PROVES g(y)的伽罗瓦群 <-> g(y) DEPENDS_ON 伽罗瓦基本定理
    # Remove PROVES(353) - fundamental theorem doesn't "prove" a specific group computation
    (353, "伽罗瓦基本定理 -/-> g(y)伽罗瓦群 (基本定理不证明具体计算)"),

    # Cycle 3: 四次方程求根公式 DEPENDS_ON 三次方程求根公式 <-> 三次方程 PROVES 四次方程
    # Keep PROVES(366) since cubic formula IS used to derive quartic; remove DEPENDS_ON(360)
    (360, "四次方程求根公式 -/-> 三次方程求根公式 (反向已保留)"),

    # Cycle 4: 判别式↔四次方程伽罗瓦群
    # Keep 判别式 DEPENDS_ON 四次方程伽罗瓦群 (判别式用于计算伽罗瓦群)
    # Remove 四次方程伽罗瓦群 DEPENDS_ON 判别式 (364)
    (364, "四次方程伽罗瓦群 -/-> 判别式 (反向已保留)"),

    # Cycle 5: 定理6 PROVES Cauchy不等式 <-> Cauchy不等式 DEPENDS_ON 定理6
    # Remove DEPENDS_ON(472) - Cauchy不等式 doesn't "depend on" 定理6 (it IS the theorem)
    (472, "Cauchy不等式 -/-> 定理6 (Cauchy不等式即定理6)"),

    # Cycle 6: 整函数 GENERALIZES 超越整函数 <-> 超越整函数 EXAMPLE_OF 整函数
    # Keep GENERALIZES(478); remove EXAMPLE_OF(479) - generalization is the stronger relation
    (479, "超越整函数 -/-> 整函数 (保留GENERALIZES方向)"),

    # Cycle 7: 解析开拓 DEPENDS_ON 全纯函数唯一性 <-> 全纯函数唯一性 PROVES 解析开拓
    # Keep DEPENDS_ON(510); remove PROVES(514) - 解析开拓 builds on uniqueness, not proven by it
    (514, "全纯函数唯一性 -/-> 解析开拓 (保留DEPENDS_ON方向)"),

    # Cycle 8: 解析开拓 BUILDS_ON Abel定理 <-> Abel定理 PROVES 解析开拓
    # Keep BUILDS_ON(511); remove PROVES(515)
    (515, "Abel定理 -/-> 解析开拓 (保留BUILDS_ON方向)"),

    # Cycle 9: 解析开拓 BUILDS_ON Heine-Borel <-> Heine-Borel PROVES 解析开拓
    # Keep BUILDS_ON(512); remove PROVES(516)
    (516, "Heine-Borel -/-> 解析开拓 (保留BUILDS_ON方向)"),

    # Cycle 10: Riemann映射定理 PROVES Riemann映射唯一性 <-> 唯一性 DEPENDS_ON 定理
    # Keep PROVES(532); remove DEPENDS_ON(533)
    (533, "Riemann映射唯一性 -/-> Riemann映射定理 (保留PROVES方向)"),
]

for edge_id, reason in cycles_to_fix:
    conn.execute('DELETE FROM graph_edges WHERE id = ?', (edge_id,))
    log("CYCLE", f"Removed edge {edge_id}: {reason}")

# ============================================================
# PART 3: FIX PROVES EDGE DIRECTIONS
# ============================================================
print("\n=== PART 3: FIX PROVES DIRECTIONS ===")

# Problematic PROVES edges where direction is wrong:
# Edge 354: 伽罗瓦基本定理 PROVES 拉格朗日预解式 (already deleted as part of cycle 1 above → KEEP: theorem proves method)
# Edge 366: 三次方程求根公式 PROVES 四次方程求根公式 → CORRECT (cubic is used to derive quartic)
# Edge 353: already removed in cycle fix
# Edge 455: 全体论证 PROVES 多值函数 → likely wrong, should be APPLIES_TO or DEPENDS_ON
# Edge 471: 定理6 PROVES Cauchy不等式 → already part of cycle fix (edge 472 removed)
# Edge 575: Gauss曲率公式 PROVES Gauss曲率 → WRONG: formula defines curvature, so should be BUILDS_ON

wrong_proves = [
    # (edge_id, new_relation_type, reason)
    (455, 'DEPENDS_ON', "多值函数 depends on 全体论证 (not proven by)"),
    (575, 'BUILDS_ON', "Gauss曲率 builds on Gauss曲率公式 (formula defines concept)"),
]

for edge_id, new_rel, reason in wrong_proves:
    conn.execute('UPDATE graph_edges SET relation_type = ? WHERE id = ?', (new_rel, edge_id))
    log("PROVES", f"Changed edge {edge_id} to {new_rel}: {reason}")

# ============================================================
# PART 4: FIX OCR ARTIFACTS
# ============================================================
print("\n=== PART 4: FIX OCR ARTIFACTS ===")

# Search for "U 二 C" pattern (OCR of U ⊂ C) and "V 二 C" (OCR of V ⊂ C)
ocr_nodes = conn.execute(
    "SELECT id, name, content FROM graph_nodes WHERE content LIKE '%\u4e8c C%' OR content LIKE '%\u4e8cC%'"
).fetchall()
print(f"  Found {len(ocr_nodes)} nodes with '二 C' pattern")

for n in ocr_nodes:
    old_content = n['content'] or ''
    new_content = old_content.replace('U 二 C', 'U ⊂ C').replace('V 二 C', 'V ⊂ C')
    new_content = new_content.replace('U二C', 'U ⊂ C').replace('V二C', 'V ⊂ C')
    if new_content != old_content:
        conn.execute('UPDATE graph_nodes SET content = ? WHERE id = ?', (new_content, n['id']))
        log("OCR", f"Fixed OCR in node {n['id'][:8]}: {n['name'][:30]}")

# Also check for other common OCR/encoding artifacts
# Fix garbled chapter names
garbled_chapters = conn.execute(
    "SELECT id, chapter FROM graph_nodes WHERE chapter LIKE '%OOOOOO%' OR chapter LIKE '%J''%'"
).fetchall()
print(f"  Found {len(garbled_chapters)} nodes with garbled chapters")
# These are severe OCR failures - clear them
for g in garbled_chapters:
    conn.execute('UPDATE graph_nodes SET chapter = ? WHERE id = ?',
                 ('[待修复: OCR 残留]', g['id']))

# ============================================================
# COMMIT AND VERIFY
# ============================================================
conn.commit()

# Quick verification
print("\n=== VERIFICATION ===")
new_isolated = conn.execute('''
    SELECT COUNT(*) as cnt FROM graph_nodes n
    WHERE n.id NOT IN (SELECT source_id FROM graph_edges UNION SELECT target_id FROM graph_edges)
''').fetchone()['cnt']

new_cycles = conn.execute('''
    SELECT COUNT(*) as cnt FROM
    (SELECT e1.id FROM graph_edges e1
     JOIN graph_edges e2 ON e1.source_id = e2.target_id AND e1.target_id = e2.source_id AND e1.id < e2.id)
''').fetchone()['cnt']

new_dups = conn.execute('''
    SELECT COUNT(*) as cnt FROM
    (SELECT book_id, name, COUNT(*) as c FROM graph_nodes GROUP BY book_id, name HAVING c > 1)
''').fetchone()['cnt']

total_nodes = conn.execute('SELECT COUNT(*) as cnt FROM graph_nodes').fetchone()['cnt']
total_edges = conn.execute('SELECT COUNT(*) as cnt FROM graph_edges').fetchone()['cnt']

print(f"  Nodes: {total_nodes} (was 322)")
print(f"  Edges: {total_edges} (was 292)")
print(f"  Isolated: {new_isolated} (was 60)")
print(f"  Cycles: {new_cycles} (was 10)")
print(f"  Exact duplicates: {new_dups} (was ~0)")

print(f"\n=== CHANGES SUMMARY ===")
print(f"  Total changes: {len(changes)}")
for c in changes:
    print(c)

conn.close()
print("\n[DONE] Structural fixes applied. Isolated node connections need separate handling.")
