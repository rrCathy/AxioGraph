import requests, time, os, glob

BASE = "http://localhost:8001/api/books"

def get_books():
    return requests.get(f"{BASE}/").json()

def delete_book(bid):
    requests.delete(f"{BASE}/{bid}")

def upload(pdf_path):
    fname = os.path.basename(pdf_path)
    fsize = os.path.getsize(pdf_path) / 1e6
    print(f"Uploading: {fname} ({fsize:.1f} MB)")
    with open(pdf_path, "rb") as f:
        r = requests.post(f"{BASE}/upload", files={"file": (fname, f)})
    data = r.json()
    print(f"  Book ID: {data['id']}")
    return data["id"]

def wait_for(book_id, timeout=600):
    print(f"  Waiting for extraction...")
    elapsed = 0
    while elapsed < timeout:
        time.sleep(5)
        elapsed += 5
        r = requests.get(f"{BASE}/{book_id}")
        b = r.json()
        status = b["status"]
        pct = b.get("progress", 0)
        nodes = b.get("node_count", 0)
        edges = b.get("edge_count", 0)
        print(f"    [{status[:25]:25s}] progress={pct}% nodes={nodes} edges={edges}")
        if status != "pending" and status != "checking" and status != "parsing" and status != "extracting":
            print(f"  Done! Status: {status}")
            return status
    print(f"  Timeout after {timeout}s")
    return "timeout"

# Clean up
books = get_books()
for b in books:
    print(f"Deleting: {b['title'][:40]} ({b['id'][:8]}...)")
    delete_book(b["id"])
time.sleep(2)
print("Cleaned.\n")

# Upload and process one book
test_dir = r"C:\newproject\AxioGraph\tests"
pdfs = sorted(glob.glob(os.path.join(test_dir, "*.pdf")))

# Pick first 2 books (Chinese + English)
targets = [pdfs[0], pdfs[-2]]  # 代数学方法 + Serre
for pdf_path in targets:
    bid = upload(pdf_path)
    wait_for(bid, timeout=600)
    print()
