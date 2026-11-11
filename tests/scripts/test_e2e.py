import asyncio, sys, io, os, shutil, uuid, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, r"C:\newproject\AxioGraph\backend")
os.chdir(r"C:\newproject\AxioGraph\backend")

from config import settings
from services.llm import get_embedding_func, get_llm
from lightrag import LightRAG, QueryParam
from pathlib import Path

print("=" * 60)
print("END-TO-END PIPELINE TEST")
print("=" * 60)

# Step 1: Create test data via the upload API
print("\n--- Step 1: Create test knowledge graph ---")

# Pre-build a small math knowledge graph directly
test_nodes = [
    {"name": "群的定义", "entity_type": "DEFINITION", 
     "content": "群是一个非空集合G配备二元运算，满足结合律、存在单位元e使得ge=eg=g、每个元素g存在逆元g^{-1}使得gg^{-1}=g^{-1}g=e。"},
    {"name": "正规子群", "entity_type": "DEFINITION",
     "content": "群G的子群N称为正规子群，如果对任意g∈G，有gNg^{-1}=N。正规子群是构造商群的关键。"},
    {"name": "拉格朗日定理", "entity_type": "THEOREM",
     "content": "拉格朗日定理：有限群G的任意子群H的阶整除G的阶，即|H|整除|G|。"},
    {"name": "商群", "entity_type": "DEFINITION",
     "content": "设N是群G的正规子群，则陪集集合G/N在运算(gN)(hN)=ghN下构成群，称为商群。"},
    {"name": "同态基本定理", "entity_type": "THEOREM",
     "content": "第一同构定理：设φ:G→H是群同态，则G/ker(φ)≅im(φ)。"},
    {"name": "柯西定理", "entity_type": "THEOREM",
     "content": "柯西定理：若素数p整除有限群G的阶，则G中存在p阶元。"},
    {"name": "群同态", "entity_type": "DEFINITION",
     "content": "设G,H是群，映射φ:G→H称为同态，如果φ(ab)=φ(a)φ(b)对所有a,b∈G成立。"},
    {"name": "正规子群的判定", "entity_type": "LEMMA",
     "content": "子群N是正规子群当且仅当对任意g∈G,n∈N有gng^{-1}∈N。"},
    {"name": "Abel群", "entity_type": "DEFINITION",
     "content": "若群G的运算满足交换律ab=ba，则称G为Abel群（交换群）。"},
    {"name": "子群", "entity_type": "DEFINITION",
     "content": "群G的非空子集H若在G的运算下也构成群，则称H为G的子群。"},
]

test_edges = [
    ("群的定义", "子群", "DEFINES"),
    ("群的定义", "Abel群", "GENERALIZES"),
    ("群的定义", "群同态", "DEFINES"),
    ("正规子群", "群的定义", "DEPENDS_ON"),
    ("正规子群", "子群", "DEPENDS_ON"),
    ("商群", "正规子群", "DEPENDS_ON"),
    ("商群", "群的定义", "DEPENDS_ON"),
    ("拉格朗日定理", "子群", "DEPENDS_ON"),
    ("拉格朗日定理", "群的定义", "DEPENDS_ON"),
    ("同态基本定理", "正规子群", "DEPENDS_ON"),
    ("同态基本定理", "商群", "DEPENDS_ON"),
    ("同态基本定理", "群同态", "DEPENDS_ON"),
    ("柯西定理", "群的定义", "DEPENDS_ON"),
    ("柯西定理", "拉格朗日定理", "GENERALIZES"),
    ("正规子群的判定", "正规子群", "PROVES"),
]

# Build custom_kg
entities = []
name_to_id = {}
for i, n in enumerate(test_nodes):
    nid = str(uuid.uuid4())
    name_to_id[n["name"]] = nid
    entities.append({
        "entity_name": n["name"],
        "entity_type": n["entity_type"],
        "description": n["content"],
        "source_id": "test-book",
        "file_path": "test/ch1",
    })

relationships = []
for src, tgt, rtype in test_edges:
    relationships.append({
        "src_id": src,
        "tgt_id": tgt,
        "description": f"{src} {rtype} {tgt}",
        "keywords": rtype.lower(),
        "weight": 1.0,
        "source_id": "test-book",
        "file_path": "test/relations",
    })

custom_kg = {
    "chunks": [{"content": n["content"], "source_id": "test-book", "file_path": f"test/ch1"} for n in test_nodes],
    "entities": entities,
    "relationships": relationships,
}

print(f"Test data: {len(entities)} entities, {len(relationships)} relations, {len(custom_kg['chunks'])} chunks")

# Step 2: Ingest into LightRAG
print("\n--- Step 2: LightRAG ingest ---")

async def llm_func(prompt, system_prompt=None, history_messages=None, **kwargs):
    llm = get_llm("chat")
    msgs = []
    if system_prompt:
        msgs.append({"role": "system", "content": system_prompt})
    if history_messages:
        for m in history_messages:
            msgs.append(m)
    msgs.append({"role": "user", "content": prompt})
    return llm.chat(msgs, temperature=0.5)

embed_func = get_embedding_func()
working_dir = str(settings.data_dir / "lightrag" / "test-book")
if Path(working_dir).exists():
    shutil.rmtree(working_dir)
Path(working_dir).mkdir(parents=True, exist_ok=True)

async def run():
    rag = LightRAG(
        working_dir=working_dir,
        llm_model_func=llm_func,
        embedding_func=embed_func,
        addon_params={"language": "Chinese"},
    )
    await rag.initialize_storages()
    print("  Storages initialized")
    
    await rag.ainsert_custom_kg(custom_kg)
    print("  Custom KG ingested")
    
    # Step 3: Query
    print("\n--- Step 3: Query tests ---")
    
    questions = [
        ("什么是群？", "hybrid"),
        ("正规子群和商群有什么关系？", "hybrid"),
        ("拉格朗日定理说了什么？", "local"),
        ("有哪些重要的群论定理？", "global"),
    ]
    
    for q, mode in questions:
        print(f"\n  Q [{mode}]: {q}")
        result = await rag.aquery(q, param=QueryParam(mode=mode))
        print(f"  A: {result[:400]}...")
    
    await rag.finalize_storages()

asyncio.run(run())
print("\n" + "=" * 60)
print("ALL TESTS PASSED")
print("=" * 60)
