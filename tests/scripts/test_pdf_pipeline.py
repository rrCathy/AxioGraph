import requests, time, os, glob, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://localhost:8001/api/books"
test_dir = r"C:\newproject\AxioGraph\tests"

# Clean
books = requests.get(f"{BASE}/").json()
for b in books:
    requests.delete(f"{BASE}/{b['id']}")
time.sleep(1)

# Upload algebra book
pdfs = sorted(glob.glob(os.path.join(test_dir, "*.pdf")))
target = pdfs[0]  # 代数学方法_卷一_李文威.pdf (3.6MB)
fname = os.path.basename(target)
print(f"Uploading: {fname}")
with open(target, "rb") as f:
    r = requests.post(f"{BASE}/upload", files={"file": (fname, f)})
book_id = r.json()["id"]
print(f"Book ID: {book_id}\n")

print("Monitoring (extraction via FreeLLMAPI)...")
for i in range(120):
    time.sleep(5)
    r = requests.get(f"{BASE}/{book_id}")
    b = r.json()
    status = b["status"]
    pct = b.get("progress", 0)
    nodes = b.get("node_count", 0)
    edges = b.get("edge_count", 0)
    elapsed = (i+1) * 5
    if i % 4 == 0:
        print(f"  [{elapsed}s] {status[:40]} pct={pct}% nodes={nodes} edges={edges}")
    if status not in ("pending", "checking", "parsing", "extracting"):
        print(f"\nDone! {status}")
        print(f"Nodes: {nodes}, Edges: {edges}")
        break
else:
    print("TIMEOUT")
    # Get latest even if not done
    r = requests.get(f"{BASE}/{book_id}")
    b = r.json()
    print(f"Current: {b['status']} pct={b.get('progress',0)}% nodes={b.get('node_count',0)}")

# Test chat if nodes found
if b.get("node_count", 0) > 0:
    print("\n--- Chat Test ---")
    r = requests.post("http://localhost:8001/api/chat/ask", json={
        "question": "什么是群？",
        "book_id": book_id
    }, timeout=60)
    data = r.json()
    print(f"A: {data.get('answer','')[:500]}")
