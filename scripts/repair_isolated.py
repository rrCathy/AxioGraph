"""
Knowledge Graph Repair - Part 2 (FIXED): Connect Isolated Nodes
Uses mathematical domain knowledge to add edges from isolated nodes
into the connected graph.
"""
import sqlite3
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DB = r'C:\newproject\AxioGraph\data\axiograph.db'

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

GALOIS = '401353c5-f45b-4008-b594-e2aa3261013a'
COMPLEX = 'a0eae8c3-916d-4ca7-a36f-a0bd38cd6617'

edges_added = 0

def add_edge(source_id, target_id, relation, book_id, desc=""):
    """Add edge if source and target exist and edge doesn't already exist."""
    global edges_added
    src = conn.execute('SELECT id, name FROM graph_nodes WHERE id=?', (source_id,)).fetchone()
    tgt = conn.execute('SELECT id, name FROM graph_nodes WHERE id=?', (target_id,)).fetchone()
    if not src:
        print(f'  SKIP: source missing {source_id[:8]}')
        return False
    if not tgt:
        print(f'  SKIP: target missing {target_id}')
        return False
    if source_id == target_id:
        print(f'  SKIP: self-reference {src["name"][:30]}')
        return False
    exist = conn.execute(
        'SELECT id FROM graph_edges WHERE source_id=? AND target_id=? AND relation_type=?',
        (source_id, target_id, relation)
    ).fetchone()
    if exist:
        print(f'  SKIP: edge exists {src["name"][:20]} -> {tgt["name"][:20]}')
        return False
    conn.execute(
        'INSERT INTO graph_edges (source_id, target_id, relation_type, description, book_id) VALUES (?,?,?,?,?)',
        (source_id, target_id, relation, desc, book_id)
    )
    edges_added += 1
    print(f'  OK: [{relation}] {src["name"][:30]} -> {tgt["name"][:30]}')
    return True

def find_node(book_id, name_pattern, exclude_id=None):
    """Find a connected node by partial name match, optionally excluding an id."""
    rows = conn.execute(
        'SELECT id, name FROM graph_nodes WHERE book_id=? AND name LIKE ? ORDER BY name',
        (book_id, f'%{name_pattern}%')
    ).fetchall()
    for r in rows:
        if exclude_id and r['id'] == exclude_id:
            continue
        # Prefer nodes that have edges (connected)
        has_edges = conn.execute(
            'SELECT 1 FROM graph_edges WHERE source_id=? OR target_id=? LIMIT 1',
            (r['id'], r['id'])
        ).fetchone()
        if has_edges:
            return r['id']
    # Fallback: return first non-excluded
    for r in rows:
        if exclude_id and r['id'] == exclude_id:
            continue
        return r['id']
    return None

# ============================================================
print("\n=== CONNECT ISOLATED NODES - 伽罗瓦理论 (13 nodes) ===")

# DEFINITION: 多项式 g(x)=x^n-a 的伽罗瓦群 C_g
tgt = find_node(GALOIS, '伽罗瓦群的定义')
add_edge('2d3a5acc-dc59-4cb3-bd80-b5ce17f6e4a2', tgt, 'DEPENDS_ON', GALOIS)

# DEFINITION: 对称多项式 s(r1,...,rn)
tgt = find_node(GALOIS, '初等对称多项式')
add_edge('c4e28020-b9be-4f1a-9deb-3950ce6b67d1', tgt, 'DEPENDS_ON', GALOIS)

# DEFINITION: 模 p 同态
tgt = find_node(GALOIS, '剩余类加群')
add_edge('5699fba3-c5a1-4e34-bacb-f418c29ea2be', tgt, 'BUILDS_ON', GALOIS)

# DEFINITION: 正规扩张/伽罗瓦扩张定义 (Def 10.13)
tgt = find_node(GALOIS, '伽罗瓦群的定义')
add_edge('36ed39c6-54cd-4e59-8f6e-3ab369be685e', tgt, 'BUILDS_ON', GALOIS)

# DEFINITION: 群的中心
tgt = find_node(GALOIS, '正规子群')
add_edge('4dc45cbb-d918-496d-b778-722c4ce8d7cf', tgt, 'DEPENDS_ON', GALOIS)

# LEMMA: Lemma 5.5
tgt = find_node(GALOIS, '四次方程的伽罗瓦群')
add_edge('556cb229-2f3c-4f6b-9ac4-9f63495e587b', tgt, 'BUILDS_ON', GALOIS)

# LEMMA: 引理3.6(ii) x^n-a 分裂域与循环群子群同构
tgt = find_node(GALOIS, '定理3.4')
add_edge('171fcc88-05d6-4897-8e1f-c8b9490fafcc', tgt, 'BUILDS_ON', GALOIS)

# LEMMA: 引理3.6(iii) Gal(E/F)→子群H的单同态
tgt = find_node(GALOIS, '伽罗瓦群的定义')
add_edge('60ccf6cc-7233-4e78-aa5e-b9afccedc3d7', tgt, 'BUILDS_ON', GALOIS)

# LEMMA: 引理3.6(iv) 素数指数扩张伽罗瓦群同构
tgt = find_node(GALOIS, '伽罗瓦群的定义')
add_edge('22878cf4-70bd-4584-bb4a-85d171f225b9', tgt, 'BUILDS_ON', GALOIS)

# PROPOSITION: 阿贝尔群子群正规性命题
tgt = find_node(GALOIS, '正规子群')
add_edge('34829e0a-5d54-4d45-8267-427620c18e7e', tgt, 'BUILDS_ON', GALOIS)

# THEOREM: 可分性封闭性质 Theorem 10.12
tgt = find_node(GALOIS, '代数扩张的传递性定理')
add_edge('bc30827c-ca11-444a-ba5e-389d0de47f3b', tgt, 'DEPENDS_ON', GALOIS)

# THEOREM: 有限可分扩张是单扩张 Theorem 10.11
tgt = find_node(GALOIS, '单扩域的结构定理')
add_edge('1e19ebb1-cf51-46ab-a796-fef126884ee8', tgt, 'GENERALIZES', GALOIS)

# THEOREM: 有限正规扩张与伽罗瓦扩张的刻画 Theorem 10.14
tgt = find_node(GALOIS, '伽罗瓦基本定理')
add_edge('dd86f150-a1ad-49cb-8629-75b523e66d38', tgt, 'BUILDS_ON', GALOIS)

print(f"\n  Galois sub-total: {edges_added}")

# ============================================================
print("\n=== CONNECT ISOLATED NODES - 简明复分析 (47 nodes) ===")

# --- CRITICAL THEOREMS ---

tgt = find_node(COMPLEX, '解析函数')
add_edge('eb519dbc-cce4-49d3-a117-0aca021118e5', tgt, 'BUILDS_ON', COMPLEX)  # Cauchy-Riemann

tgt = find_node(COMPLEX, '唯一性定理')
add_edge('1b0f41cd-4ae5-46b0-b3bf-ed6f619e7953', tgt, 'BUILDS_ON', COMPLEX)  # Hurwitz

tgt = find_node(COMPLEX, '开映射定理')
add_edge('a84b37e4-605d-4868-8756-089e60558d13', tgt, 'DEPENDS_ON', COMPLEX)  # Rouche

tgt = find_node(COMPLEX, 'Reinhardt')
add_edge('88fc7f8d-3db2-4c53-b49b-5535cca97e23', tgt, 'DEPENDS_ON', COMPLEX)  # Poincare

tgt = find_node(COMPLEX, '解析函数')
add_edge('6e62c0a0-145f-45dc-94a3-4b5f11a75ea8', tgt, 'BUILDS_ON', COMPLEX)  # 最大模原理

tgt = find_node(COMPLEX, '全纯函数')
add_edge('d69daee3-ff5f-4ccd-8275-e88c9967788c', tgt, 'BUILDS_ON', COMPLEX)  # 保角性定理

tgt = find_node(COMPLEX, 'Laurent')
add_edge('df119c5f-1d96-47fc-8863-40f2ab40304f', tgt, 'DEPENDS_ON', COMPLEX)  # Laurent展开定理

tgt = find_node(COMPLEX, '全纯函数')
add_edge('14aa51a2-ebc8-4095-9385-81de8678159e', tgt, 'BUILDS_ON', COMPLEX)  # 常数性判据

# 对称原理（定理6'）-> 对称原理 (exclude self)
tgt = find_node(COMPLEX, '对称原理', exclude_id='5cb58525-97ca-4bac-88a9-2078085fe582')
add_edge('5cb58525-97ca-4bac-88a9-2078085fe582', tgt, 'EQUIVALENT_TO', COMPLEX)

tgt = find_node(COMPLEX, '全纯自同构')
add_edge('d39de318-4878-46b7-9890-541877c7dba1', tgt, 'BUILDS_ON', COMPLEX)  # 单位圆自同构群

tgt = find_node(COMPLEX, 'Weierstrass 因子分解')
add_edge('da74d409-4bf9-4cf5-8403-74bbebb2a399', tgt, 'BUILDS_ON', COMPLEX)  # 无穷乘积

tgt = find_node(COMPLEX, 'Riemann 映射定理')
add_edge('5f58d25f-2b64-4888-963c-bcf35bfb8afc', tgt, 'GENERALIZES', COMPLEX)  # Poincare-Koebe

tgt = find_node(COMPLEX, '调和函数')
add_edge('d269aee1-0607-43fe-8357-695e3a8bfd88', tgt, 'BUILDS_ON', COMPLEX)  # Dirichlet/Poisson

# --- BASIC THEOREMS ---
tgt = find_node(COMPLEX, '可微')
add_edge('05abc1a5-f603-44f6-b609-21df1d77548a', tgt, 'BUILDS_ON', COMPLEX)  # 微分中值
add_edge('97452368-2a87-4701-bd0a-0b4f0087d9da', tgt, 'BUILDS_ON', COMPLEX)  # 微积分基本(微分)
add_edge('b3b6816b-4e17-47de-b31a-534722e78b8f', tgt, 'BUILDS_ON', COMPLEX)  # 微积分基本(积分)
add_edge('bb09b9b9-a183-48d5-a17c-1ff250c1dce3', tgt, 'BUILDS_ON', COMPLEX)  # 积分中值

tgt = find_node(COMPLEX, '整函数')
add_edge('3ac6df7d-4998-44b0-8c40-f7c44c2b43f6', tgt, 'BUILDS_ON', COMPLEX)  # U(z)整函数
add_edge('7ea80b83-1864-4ad5-964c-7e4fac805344', tgt, 'BUILDS_ON', COMPLEX)  # 零点分布

tgt = find_node(COMPLEX, '复指数函数')
add_edge('2ea3a3b2-66b7-4c25-8172-7f1f01a15e73', tgt, 'DEPENDS_ON', COMPLEX)  # 偶函数
add_edge('d13d98a2-1697-4e98-ab7d-c02ecfed38d2', tgt, 'DEPENDS_ON', COMPLEX)  # 周期性

tgt = find_node(COMPLEX, '复数正弦函数')
add_edge('c50729cb-ae9f-4a47-9ce1-88f8de2bbe4f', tgt, 'BUILDS_ON', COMPLEX)  # 和角公式
add_edge('81706e0c-878f-4dc9-a744-e305ba3a5869', tgt, 'BUILDS_ON', COMPLEX)  # 基本关系式

tgt = find_node(COMPLEX, '对数函数')
add_edge('2185472e-b7bc-459b-b412-5070c75ccd68', tgt, 'BUILDS_ON', COMPLEX)  # 对数函数性质

# --- DEFINITIONS ---
tgt = find_node(COMPLEX, '全纯函数')
add_edge('d389af47-dab6-427c-8ff5-a343935fe0f5', tgt, 'DEPENDS_ON', COMPLEX)  # 共形映射

tgt = find_node(COMPLEX, '极点')
add_edge('5e368308-26db-4659-b46f-f9d805d9aa1b', tgt, 'DEPENDS_ON', COMPLEX)  # 留数

tgt = find_node(COMPLEX, '对数函数')
add_edge('16265ee2-ef8b-443f-9fd6-e6f310a5550a', tgt, 'BUILDS_ON', COMPLEX)  # 主值分支

tgt = find_node(COMPLEX, '可微')
add_edge('6dfc8aac-a8cb-4e55-89ef-e4d971be0d06', tgt, 'DEPENDS_ON', COMPLEX)  # 伸长度
add_edge('17202ee9-5cf9-4c01-bbd7-5ef2aea28a28', tgt, 'DEPENDS_ON', COMPLEX)  # 微商的定义

tgt = find_node(COMPLEX, 'Laurent')
add_edge('712d9f73-2227-438d-b3b8-369b7fbcea14', tgt, 'DEPENDS_ON', COMPLEX)  # 全纯部分

tgt = find_node(COMPLEX, '复指数函数')
add_edge('8e820b11-21bd-4cc4-9b8e-3bd05a27cb1d', tgt, 'DEPENDS_ON', COMPLEX)  # 初等函数

tgt = find_node(COMPLEX, '复数余弦函数')
add_edge('2ff345bb-5f7b-4cb8-bf8f-af53cf2a1688', tgt, 'DEPENDS_ON', COMPLEX)  # 复数反余弦

tgt = find_node(COMPLEX, '解析函数')
add_edge('7687bcc9-d661-4b94-991a-3985f51acbdd', tgt, 'EXAMPLE_OF', COMPLEX)  # 多项式

tgt = find_node(COMPLEX, '单连通域')
add_edge('7a7de8d0-b4e8-431a-8668-6c2e80ebc3ea', tgt, 'EXAMPLE_OF', COMPLEX)  # 带域Ek

tgt = find_node(COMPLEX, '极点')
add_edge('1c90ef83-59f4-48bc-9d1c-e05f3f90e118', tgt, 'BUILDS_ON', COMPLEX)  # 无穷远点极点

tgt = find_node(COMPLEX, '可去奇点')
add_edge('3e6eb760-8f03-41c0-93e8-9ccb8ea03693', tgt, 'BUILDS_ON', COMPLEX)  # 无穷远点可去奇点

tgt = find_node(COMPLEX, '奇点')
add_edge('7c5ebb90-7648-4d3a-b5a4-9efcda549bf9', tgt, 'BUILDS_ON', COMPLEX)  # 无穷远点本性奇点

tgt = find_node(COMPLEX, '简单曲线')
add_edge('7b938986-601b-4013-a127-afdad22dd88f', tgt, 'BUILDS_ON', COMPLEX)  # 曲线端点

tgt = find_node(COMPLEX, '有理函数')
add_edge('f2ff239c-391c-4d66-9d8d-0aa0e0793b03', tgt, 'BUILDS_ON', COMPLEX)  # 有理分式

# --- EXAMPLES ---
tgt = find_node(COMPLEX, 'Weierstrass 定理')
add_edge('3142749e-1dcc-4b98-a11b-28c31cd43336', tgt, 'EXAMPLE_OF', COMPLEX)  # 例6

tgt = find_node(COMPLEX, '留数公式')
add_edge('f3684cde-172e-4b90-a033-2fa028aab769', tgt, 'EXAMPLE_OF', COMPLEX)  # Fresnel积分
add_edge('e0ac8084-09d2-4721-b817-95f55ece15d2', tgt, 'EXAMPLE_OF', COMPLEX)  # Dirichlet积分

tgt = find_node(COMPLEX, 'Picard 小定理')
add_edge('89019aeb-d17f-42a9-b597-81058770fd27', tgt, 'EXAMPLE_OF', COMPLEX)  # 整函数映射缺口

# --- LEMMAS ---
tgt = find_node(COMPLEX, 'Taylor-Maclaurin')
add_edge('ec4fa7e4-3c7a-44df-a808-2571a7b11324', tgt, 'BUILDS_ON', COMPLEX)  # Lemma 2

# Schwarz-Christoffel: use %Schwarz% without dash to avoid unicode mismatch
tgt = find_node(COMPLEX, 'Schwarz')
# But narrow to one with "映射定理" or "映射 f" - prefer 映射定理
rows = conn.execute(
    "SELECT id, name FROM graph_nodes WHERE book_id=? AND name LIKE '%Schwarz%' ORDER BY name",
    (COMPLEX,)
).fetchall()
sc_target = None
for r in rows:
    if '映射定理' in r['name']:
        sc_target = r['id']
        break
if not sc_target:
    for r in rows:
        if '映射' in r['name']:
            sc_target = r['id']
            break
if not sc_target and rows:
    sc_target = rows[0]['id']
add_edge('4ae87ad4-3057-40af-817f-c2623c11afe3', sc_target, 'BUILDS_ON', COMPLEX)  # SC极限引理

# --- PROPOSITIONS ---
tgt = find_node(COMPLEX, '全纯自同构')
add_edge('f5ab54d9-0725-4526-b116-e8872096a590', tgt, 'BUILDS_ON', COMPLEX)  # 单位球自同构群

tgt = find_node(COMPLEX, 'Poincar')
add_edge('e97c8349-a03d-4233-95f3-fa3d72831277', tgt, 'BUILDS_ON', COMPLEX)  # Poincare距离

# ============================================================
# COMMIT
conn.commit()
print(f"\n=== RESULTS ===")
print(f"  Total edges added: {edges_added}")

# ============================================================
# FIX REMAINING CYCLES
print(f"\n=== FIX REMAINING CYCLES ===")
cycles = conn.execute('''
    SELECT e1.id as id1, e2.id as id2, e1.relation_type as r1, e2.relation_type as r2,
           n1.name as src, n2.name as tgt
    FROM graph_edges e1
    JOIN graph_edges e2 ON e1.source_id = e2.target_id AND e1.target_id = e2.source_id AND e1.id < e2.id
    JOIN graph_nodes n1 ON e1.source_id = n1.id
    JOIN graph_nodes n2 ON e1.target_id = n2.id
''').fetchall()
for c in cycles:
    print(f'  Cycle: {c["src"][:30]} [{c["r1"]}] {c["tgt"][:30]} | {c["tgt"][:30]} [{c["r2"]}] {c["src"][:30]}')
    conn.execute('DELETE FROM graph_edges WHERE id = ?', (c['id2'],))
    print(f'  -> Removed edge {c["id2"]}')
conn.commit()

# ============================================================
# FINAL STATS
print(f"\n=== FINAL CONNECTIVITY ===")
for bid, label in [(GALOIS, '伽罗瓦理论'), (COMPLEX, '简明复分析')]:
    total = conn.execute('SELECT COUNT(*) as cnt FROM graph_nodes WHERE book_id=?', (bid,)).fetchone()['cnt']
    connected = conn.execute('''
        SELECT COUNT(DISTINCT n.id) as cnt FROM graph_nodes n
        WHERE n.book_id=? AND n.id IN (
            SELECT source_id FROM graph_edges UNION SELECT target_id FROM graph_edges
        )
    ''', (bid,)).fetchone()['cnt']
    isolated = total - connected
    edges = conn.execute('SELECT COUNT(*) as cnt FROM graph_edges WHERE book_id=?', (bid,)).fetchone()['cnt']
    pct = isolated * 100 // total if total else 0
    print(f'  {label}: {total} nodes, {edges} edges, {connected} connected, {isolated} isolated ({pct}%)')

# Remaining isolated nodes
remaining = conn.execute('''
    SELECT n.id, n.book_id, n.entity_type, n.name FROM graph_nodes n
    WHERE n.id NOT IN (SELECT source_id FROM graph_edges UNION SELECT target_id FROM graph_edges)
    ORDER BY n.book_id, n.entity_type, n.name
''').fetchall()
if remaining:
    print(f'\n  Remaining isolated: {len(remaining)}')
    for r in remaining:
        print(f'    [{r["book_id"][:8]}] {r["entity_type"]:12s} | {r["name"][:60]}')

conn.close()
print("\n[DONE]")
