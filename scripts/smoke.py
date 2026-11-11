"""AxioGraph dev smoke check.

Run after `start.ps1`:
    python scripts/smoke.py

Exits 0 when the local stack is ready to work on. LLM availability is a
warning, not a failure: browsing existing graphs does not need a model server.
"""
import json
import sys
import urllib.error
import urllib.request

BACKEND = "http://127.0.0.1:8000"
FRONTEND = "http://127.0.0.1:5173"

# The ambient HTTP_PROXY must not swallow loopback requests.
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

failures = []
warnings = []


def get(url, timeout=8):
    with OPENER.open(url, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", "replace")


def check(label, fn):
    try:
        detail = fn()
        print(f"[PASS] {label}" + (f" - {detail}" if detail else ""))
        return True
    except Exception as e:
        print(f"[FAIL] {label} - {type(e).__name__}: {str(e)[:160]}")
        failures.append(label)
        return False


def c_health():
    code, body = get(f"{BACKEND}/api/health")
    assert code == 200 and json.loads(body).get("status") == "ok", body[:120]
    return "status=ok"


def c_books():
    global BOOKS
    code, body = get(f"{BACKEND}/api/books/")
    BOOKS = json.loads(body)
    assert code == 200 and isinstance(BOOKS, list) and BOOKS, f"books={BOOKS!r}"[:160]
    return f"{len(BOOKS)} book(s)"


def c_graph():
    total_nodes = total_edges = 0
    for b in BOOKS:
        code, body = get(f"{BACKEND}/api/graph/{b['id']}")
        elements = json.loads(body)["elements"]
        nodes = {n["data"]["id"] for n in elements["nodes"]}
        edges = elements["edges"]
        bad = [e for e in edges
               if e["data"]["source"] not in nodes or e["data"]["target"] not in nodes]
        assert nodes and edges, f"{b['title']}: empty graph"
        assert not bad, f"{b['title']}: {len(bad)} dangling edges"
        assert (len(nodes), len(edges)) == (b["node_count"], b["edge_count"]), \
            f"{b['title']}: counters {b['node_count']}/{b['edge_count']} != {len(nodes)}/{len(edges)}"
        total_nodes += len(nodes)
        total_edges += len(edges)
    return f"{total_nodes} nodes / {total_edges} edges, no dangling edges, counters in sync"


def c_node_detail():
    _, body = get(f"{BACKEND}/api/graph/{BOOKS[0]['id']}")
    nid = json.loads(body)["elements"]["nodes"][0]["data"]["id"]
    code, detail = get(f"{BACKEND}/api/graph/node/{nid}")
    assert code == 200 and json.loads(detail).get("id") == nid
    return f"node {nid[:8]}"


def c_frontend():
    code, body = get(FRONTEND)
    assert code == 200 and "<div id=\"root\"" in body, f"unexpected index (status {code})"
    return "index served"


def c_proxy():
    code, body = get(f"{FRONTEND}/api/health")
    assert code == 200 and json.loads(body).get("status") == "ok"
    return "/api proxied to backend"


def c_llm():
    code, body = get(f"{BACKEND}/api/health/llm", timeout=20)
    llm = json.loads(body)["llm"]
    down = [f"{k}: {v.get('error', 'empty response')}" for k, v in llm.items() if not v.get("ok")]
    if down:
        warnings.append("LLM unavailable - upload / chat / translate / extraction need the local model server")
        for d in down:
            print(f"       {d}")
        return None
    return "extraction + chat reachable"


print("=" * 62)
print("AxioGraph smoke check")
print("=" * 62)

check("backend /api/health", c_health)
check("books list", c_books)
if not failures:
    check("graph for every book", c_graph)
    check("node detail endpoint", c_node_detail)
    check("frontend index", c_frontend)
    check("frontend /api proxy", c_proxy)

    print("-" * 62)
    try:
        detail = c_llm()
        if detail:
            print(f"[PASS] LLM - {detail}")
        else:
            print("[WARN] LLM - local model server is down (graph browsing still works)")
    except Exception as e:
        warnings.append("LLM health probe failed")
        print(f"[WARN] LLM probe - {type(e).__name__}: {str(e)[:160]}")

print("-" * 62)
if failures:
    print(f"NOT READY: {len(failures)} failure(s). Start the stack with .\\start.ps1")
    sys.exit(1)
print("READY: http://127.0.0.1:5173")
if warnings:
    for w in warnings:
        print(f"  note: {w}")
sys.exit(0)
