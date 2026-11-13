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
BOOKS = []
PAGE_BOOK = None


def get(url, timeout=8):
    with OPENER.open(url, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", "replace")


def get_raw(url, timeout=8):
    with OPENER.open(url, timeout=timeout) as resp:
        return resp.status, resp.headers.get("Content-Type", ""), resp.read()


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
    empty_books = 0
    for b in BOOKS:
        code, body = get(f"{BACKEND}/api/graph/{b['id']}")
        elements = json.loads(body)["elements"]
        nodes = {n["data"]["id"] for n in elements["nodes"]}
        edges = elements["edges"]
        bad = [e for e in edges
               if e["data"]["source"] not in nodes or e["data"]["target"] not in nodes]
        # A freshly imported book legitimately has no graph yet — skip it,
        # but any book WITH data must have consistent counters.
        if not nodes:
            empty_books += 1
            assert not bad
            continue
        assert not bad, f"{b['title']}: {len(bad)} dangling edges"
        assert (len(nodes), len(edges)) == (b["node_count"], b["edge_count"]), \
            f"{b['title']}: counters {b['node_count']}/{b['edge_count']} != {len(nodes)}/{len(edges)}"
        total_nodes += len(nodes)
        total_edges += len(edges)
    assert total_nodes > 0, "no book has any graph data at all"
    note = f", {empty_books} empty book(s) skipped" if empty_books else ""
    return f"{total_nodes} nodes / {total_edges} edges, no dangling edges, counters in sync{note}"


def c_node_detail():
    for b in BOOKS:
        _, body = get(f"{BACKEND}/api/graph/{b['id']}")
        nodes = json.loads(body)["elements"]["nodes"]
        if not nodes:
            continue
        nid = nodes[0]["data"]["id"]
        code, detail = get(f"{BACKEND}/api/graph/node/{nid}")
        assert code == 200 and json.loads(detail).get("id") == nid
        return f"node {nid[:8]}"
    raise AssertionError("no book with graph data")


def c_frontend():
    code, body = get(FRONTEND)
    assert code == 200 and "<div id=\"root\"" in body, f"unexpected index (status {code})"
    return "index served"


def c_proxy():
    code, body = get(f"{FRONTEND}/api/health")
    assert code == 200 and json.loads(body).get("status") == "ok"
    return "/api proxied to backend"


def c_pages():
    global PAGE_BOOK
    for b in BOOKS:
        _, body = get(f"{BACKEND}/api/books/{b['id']}/pages")
        found = json.loads(body).get("pages") or []
        if found:
            PAGE_BOOK = b["id"]
            return f"{len(found)} pages in {b['title']}"
    return None


def c_page_detail():
    # First hit may build the typed layout from scratch (layout model + OCR +
    # LaTeX engines) — allow a generous cold-start budget.
    _, body = get(f"{BACKEND}/api/books/{PAGE_BOOK}/pages/1", timeout=90)
    d = json.loads(body)
    assert d.get("page_width") and isinstance(d.get("blocks"), list), "missing bbox data"
    lay = d.get("layout") or {}
    f = (lay.get("formula_recognized"), lay.get("formula_total"))
    detail = (f"page 1: {d['char_count']} chars, {len(d['blocks'])} blocks, "
              f"{d['page_width']:.0f}pt wide")
    if lay:
        detail += f", layout v{lay.get('version')}, formulas {f[0]}/{f[1]}"
    return detail


def c_render():
    code, ctype, data = get_raw(f"{BACKEND}/api/books/{PAGE_BOOK}/pages/1/render")
    assert code == 200 and "image/png" in ctype and len(data) > 1000, "bad page image"
    return f"{len(data) // 1024} KB PNG"


def c_workbench_api():
    for path in (f"/api/books/{PAGE_BOOK}/candidates",
                 f"/api/books/{PAGE_BOOK}/confirmed-nodes"):
        code, body = get(f"{BACKEND}{path}")
        assert code == 200 and isinstance(json.loads(body), dict), path
    return "candidates + confirmed-nodes endpoints OK"


def c_llm():
    code, body = get(f"{BACKEND}/api/health/llm", timeout=20)
    llm = json.loads(body)["llm"]
    down = [f"{k}: {v.get('error', 'empty response')}" for k, v in llm.items() if not v.get("ok")]
    if down:
        timed_out = any("timed out" in d for d in down)
        warnings.append("LLM busy/unreachable - upload / chat / translate / extraction need the local model server"
                        if not timed_out else
                        "LLM health probe timed out (model busy) - extraction may still work")
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
    pages_detail = c_pages()
    if pages_detail:
        print(f"[PASS] page index - {pages_detail}")
        check("page text + bboxes", c_page_detail)
        check("original page render", c_render)
        check("workbench read APIs", c_workbench_api)
    else:
        warnings.append("no book has imported pages yet - use Re-import pages in the workbench")
        print("[WARN] page index - no imported pages yet")

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
