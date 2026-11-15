#!/usr/bin/env python3
"""Formula-level recognition benchmark grounded in arXiv LaTeX source.

Why this exists
---------------
`bench_recognition.py` measures Chinese-character fidelity against the PDF
text layer, but it cannot tell whether a *formula* was recognized correctly:
the text layer of a TeX PDF does not carry LaTeX. arXiv e-prints do. The
authors' own .tex files are therefore a human-written ground truth for every
display formula -- no manual transcription needed.

Pipeline
--------
1. Expand the e-print (.tex + \\input) in document order.
2. Extract display math (equation/align/gather/... , \\[..\\], $$..$$).
3. Locate display-formula boxes on the PDF using *text-layer geometry only*
   (math fonts, vertical gaps, centered/numbered lines). No OCR is involved
   in localization, so a weak recognizer cannot corrupt the alignment.
4. Align ground-truth formulas to PDF boxes with global sequence alignment.
5. Render each box at a given zoom/padding and run the project's own bitmap
   -> LaTeX engine (`local_recognize.latex_engine`) on it.
6. Canonicalize both sides and report exact-match rate, token F1 and
   character similarity.

Usage (from repo root or backend/)::

    python scripts/bench_formula.py --eval
    python scripts/bench_formula.py --tune
    python scripts/bench_formula.py --eval --zoom 3.0 --pad 4 --json out.json

Raw samples live in data/bench_arxiv/ (git-ignored). Re-download with:
    curl -L -o data/bench_arxiv/<id>.src https://arxiv.org/e-print/<id>
    curl -L -o data/bench_arxiv/<id>.pdf https://arxiv.org/pdf/<id>
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import re
import sys
import tarfile
import time
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DATA = ROOT / "data" / "bench_arxiv"
sys.path.insert(0, str(BACKEND))

import fitz  # noqa: E402
import numpy as np  # noqa: E402
import local_recognize as LR  # noqa: E402
import page_layout as PL  # noqa: E402

PAPERS = {
    "1706.03762": ("Attention Is All You Need", "ms.tex"),
    "2103.03874": ("Measuring Math Problem Solving", "main.tex"),
    "2504.02321": ("Shallow FFNN with Topological Inputs", "TFNNs_arXiv_rev.tex"),
    "2408.07081": ("MathBridge", "main.tex"),
}

# --------------------------------------------------------------------------
# 1. Ground truth: expand the e-print and pull display math
# --------------------------------------------------------------------------
INPUT_RE = re.compile(r"\\(?:input|include)\{([^}]+)\}")
# A real formula must carry mathematical structure. MathBridge discusses TeX
# syntax in prose (and even prints literal "$$"), so plain sentences slip in
# if we only look at delimiters.
MATH_STRUCT = re.compile(
    r"\\(?:frac|sum|sqrt|int|prod|lim|left|right|vert|Vert|mathbb|mathcal|mathrm|mathbf|vec|hat|bar|overline|sigma|varepsilon|theta|cdot|times|in|max|min|span|circ|ast|pi|sigma|varepsilon|leq|geq|neq|approx|sigma|varepsilon|partial|infty|sigma)"
    r"|[_^=]|\{|\}|\\\(|\\\)"
)


def expand_source(arxiv_id: str, main_tex: str) -> str:
    tf = tarfile.open(fileobj=io.BytesIO(gzip.decompress((DATA / f"{arxiv_id}.src").read_bytes())))
    files = {
        m.name: tf.extractfile(m).read().decode("utf-8", "ignore")
        for m in tf.getmembers()
        if m.isfile() and m.name.endswith((".tex", ".ltx"))
    }

    def resolve(key: str) -> str:
        key = key.strip()
        for cand in (key, key + ".tex", key.replace(".tex", "")):
            if cand in files:
                return files[cand]
        base = key.rsplit("/", 1)[-1]
        for name, text in files.items():
            if name.rsplit("/", 1)[-1] in (base, base + ".tex"):
                return text
        return ""

    def expand(text: str, depth: int = 0) -> str:
        if depth > 5:
            return text
        return INPUT_RE.sub(lambda m: expand(resolve(m.group(1)), depth + 1), text)

    return expand(files[main_tex])


def expand_macros(src: str) -> str:
    """Replace author-defined commands with their LaTeX bodies.

    MathBridge (2408.07081) §3: "we replaced all custom commands with their
    original LaTeX syntax equivalents" -- otherwise ground truth is full of
    opaque names like \\dmodel and cannot be compared to OCR output.
    """
    defs: dict[str, tuple[int, str]] = {}
    for m in re.finditer(
        r"\\(?:newcommand|renewcommand)\{\\([A-Za-z]+)\}(?:\[(\d)\])?\{([^{}]*)\}"
        r"|\\def\\([A-Za-z]+)\{([^{}]*)\}", src
    ):
        if m.group(1):
            defs[m.group(1)] = (int(m.group(2) or 0), m.group(3))
        else:
            defs[m.group(4)] = (0, m.group(5))
    # resolve chains (a macro may reference another macro)
    for _ in range(3):
        for name, (nargs, body) in list(defs.items()):
            for other, (on, ob) in defs.items():
                if other != name and on == 0:
                    body = body.replace("\\" + other + " ", ob + " ")
            defs[name] = (nargs, body)
        src = re.sub(r"\\(?:newcommand|renewcommand)\{\\[A-Za-z]+\}(?:\[\d\])?\{[^{}]*\}", "", src)
        src = re.sub(r"\\def\\[A-Za-z]+\{[^{}]*\}", "", src)
        for name, (nargs, body) in defs.items():
            if nargs == 0:
                src = re.sub(r"\\" + name + r"(?![A-Za-z])", lambda m, b=body: b, src)
    return src


def scan_math(src: str) -> list[tuple[str, str]]:
    """Extract math spans by sequential delimiter pairing, NOT regex.

    MathBridge §3: "$" and "$$" use the same symbol to open and close, so a
    regex mistakes a closing delimiter for an opening one. Scan left to right
    and pair each opener with the next closer instead.

    Returns (kind, body) where kind is 'display' or 'inline'.
    """
    out: list[tuple[str, str]] = []
    i, n = 0, len(src)
    env_re = re.compile(
        r"\\begin\{(equation\*?|align\*?|gather\*?|multline\*?|eqnarray\*?|displaymath)\}")
    end_re = re.compile(r"\\end\{(equation\*?|align\*?|gather\*?|multline\*?|eqnarray\*?|displaymath)\}")
    while i < n:
        c = src[i]
        if c == "%":  # TeX comment: skip to end of line
            j = src.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if src.startswith("\\$", i):
            i += 2
            continue
        if src.startswith("$$", i):
            j = src.find("$$", i + 2)
            if j > 0:
                out.append(("display", src[i + 2:j]))
                i = j + 2
                continue
        if c == "$":
            j = i + 1
            while j < n and src[j] != "$":
                if src[j] == "\\":
                    j += 1
                j += 1
            if j < n:
                out.append(("inline", src[i + 1:j]))
                i = j + 1
                continue
        if src.startswith("\\[", i):
            j = src.find("\\]", i + 2)
            if j > 0:
                out.append(("display", src[i + 2:j]))
                i = j + 2
                continue
        if src.startswith("\\(", i):
            j = src.find("\\)", i + 2)
            if j > 0:
                out.append(("inline", src[i + 2:j]))
                i = j + 2
                continue
        m = env_re.match(src, i)
        if m:
            e = end_re.search(src, m.end())
            if e:
                out.append(("display", src[m.end():e.start()]))
                i = e.end()
                continue
        i += 1
    return out


def extract_truth(src: str, inline: bool = False) -> list[str]:
    src = expand_macros(src)
    out = []
    for kind, body in scan_math(src):
        if kind != "display" and not inline:
            continue
        body = re.sub(r"(?m)(?<!\\)%.*$", "", body)
        body = re.sub(r"\\(?:label|tag)\{[^{}]*\}|\\nonumber\b|\\notag\b|\\eqno\b", "", body)
        body = body.strip()
        # Reject prose fragments / delimiter noise. MathBridge quotes LaTeX
        # syntax in running text; those must not become ground truth.
        if len(body) < 8 or not MATH_STRUCT.search(body):
            continue
        letters = len(re.findall(r"[A-Za-z]", body))
        if letters > 12 and not re.search(r"[=^_]|\\(?:frac|sum|sqrt|left|vert|mathcal|mathbb|sigma)", body):
            continue
        out.append(body)
    return out


# --------------------------------------------------------------------------
# 2. Canonicalization (applied to BOTH sides, so scoring is symmetric)
# --------------------------------------------------------------------------
SPACING_CMDS = re.compile(r"\\(?:qquad|quad|,|;|!|:|>|<|\s)")
FONT_WRAPPERS = re.compile(
    r"\\(?:mathrm|mathbf|mathit|mathsf|mathtt|mathcal|mathbb|mathfrak|text|textrm|textbf|textit|operatorname|bm|boldsymbol)"
    r"\s*\{([^{}]*)\}"
)
TOKEN_RE = re.compile(r"\\[a-zA-Z]+|\\[^a-zA-Z]|[A-Za-z0-9]|[^\s{}^_\\]")
# Semantically identical LaTeX spellings that pix2tex / authors choose
# arbitrarily. Normalized on BOTH sides so they cannot create fake errors.
EQUIV = [
    (re.compile(r"\\operatorname\*?\{?([A-Za-z]+)\}?"), r"\\\1"),
    (re.compile(r"\\(?:bf|mathbf|boldsymbol|bm)\s*\{([^{}]*)\}"), r"\\mathbf{\1}"),
    (re.compile(r"\\cal(?=[A-Za-z])"), r"\\mathcal "),
    (re.compile(r"\\(?:left|right)\s*\|"), r"\\vert "),
    (re.compile(r"\\(?:big|Big|bigg|Bigg)[lr]?\s*\|"), r"\\vert "),
    (re.compile(r"\\\|"), r"\\Vert "),
    (re.compile(r"\\(?:left|right)\s*\\Vert"), r"\\Vert "),
    (re.compile(r"\\Vert"), "||"),
    (re.compile(r"\\vert"), "|"),
    (re.compile(r"\\(?:ldots|dots|cdots)"), r"\\cdots"),
    (re.compile(r"\\varepsilon"), r"\\epsilon"),
    (re.compile(r"\\dfrac|\\tfrac|\\cfrac"), r"\\frac"),
    (re.compile(r"~+"), " "),          # pix2tex trailing padding
    (re.compile(r"\\,"), " "),
    (re.compile(r"\;"), " "),
]


def canon(s: str) -> str:
    s = re.sub(r"(?m)(?<!\\)%.*$", "", s or "")
    s = re.sub(r"\\(?:label|tag)\{[^{}]*\}|\\nonumber\b|\\notag\b|\\eqno\b", "", s)
    s = s.replace("\\left", "").replace("\\right", "")
    s = re.sub(r"\\(?:tfrac|dfrac|cfrac)", r"\\frac", s)
    s = re.sub(r"(?:\\cdot\s*){2,}", r"\\cdots ", s)
    s = s.replace("\\ldots", "\\cdots").replace("\\dots", "\\cdots")
    for _ in range(3):
        s = FONT_WRAPPERS.sub(r"\1", s)
    s = SPACING_CMDS.sub("", s)
    s = s.replace("&", "").replace("\\\\", "").replace("$", "")
    s = re.sub(r"\s+", "", s)
    s = s.replace("{", "").replace("}", "")
    for pat, rep in EQUIV:
        s = pat.sub(rep, s)
    # equation numbers embedded by the OCR ("(1.1)") are not formula content
    s = re.sub(r"\(\d+(?:\.\d+)*\)$", "", s)
    s = re.sub(r"[~\\,\s]+", "", s)
    return s.strip()


def visible(s: str) -> str:
    """Loose character stream used only for sequence *alignment*."""
    s = re.sub(r"(?m)(?<!\\)%.*$", "", s or "")
    s = re.sub(r"\\(?:label|tag|nonumber|eqno|left|right|quad|qquad)\b", "", s)
    s = re.sub(r"\\[a-zA-Z]+", "", s)
    return re.sub(r"[^a-z0-9=+*/().,^_-]", "", s.lower())


def score_pair(truth: str, pred: str) -> dict:
    a, b = canon(truth), canon(pred)
    ta, tb = Counter(TOKEN_RE.findall(a)), Counter(TOKEN_RE.findall(b))
    overlap = sum(min(ta[t], tb[t]) for t in ta)
    denom = max(1, sum(ta.values()) + sum(tb.values()))
    f1 = 2 * overlap / denom
    return {
        "exact": a == b,
        "f1": f1,
        "sim": SequenceMatcher(None, a, b, autojunk=False).ratio() if a else (1.0 if not b else 0.0),
        "truth": a,
        "pred": b,
    }


# --------------------------------------------------------------------------
# 3. PDF localization: text-layer geometry only (never uses OCR output)
# --------------------------------------------------------------------------
MATH_FONT = re.compile(r"CM(?:MI|SY|EX|BX|R|SS|TT)|MS[BA]M|EUR|Ursa|RSFS|stmary|pxsy|txsy|txmia|math", re.I)


def page_lines(page) -> list[dict]:
    rows = []
    for blk in page.get_text("dict")["blocks"]:
        if blk.get("type") != 0:
            continue
        for line in blk.get("lines", []):
            spans = line.get("spans", [])
            text = "".join(s["text"] for s in spans).strip()
            if not text:
                continue
            n = sum(len(s["text"]) for s in spans) or 1
            m = sum(len(s["text"]) for s in spans if MATH_FONT.search(str(s.get("font", ""))))
            rows.append({"bbox": list(line["bbox"]), "text": text, "math": m / n})
    rows.sort(key=lambda r: (r["bbox"][1], r["bbox"][0]))
    return rows


def page_windows(doc) -> list[list[dict]]:
    """For every PDF page, precompute candidate line windows (1-5 lines).

    TeX display formulas are split into several text-layer lines (fraction
    numerator/denominator, sub/superscripts, equation numbers), so a single
    line is rarely the whole formula.
    """
    pages = []
    for pno in range(len(doc)):
        rows = page_lines(doc[pno])
        wins = []
        for i in range(len(rows)):
            for k in (1, 2, 3, 4, 5):
                if i + k > len(rows):
                    break
                chunk = rows[i:i + k]
                x0 = min(r["bbox"][0] for r in chunk)
                y0 = min(r["bbox"][1] for r in chunk)
                x1 = max(r["bbox"][2] for r in chunk)
                y1 = max(r["bbox"][3] for r in chunk)
                if y1 - y0 > 120 or x1 - x0 < 12:
                    continue
                wins.append({
                    "page": pno + 1,
                    "bbox": [round(q, 1) for q in (x0, y0, x1, y1)],
                    "text": " ".join(r["text"] for r in chunk),
                    "vis": visible(" ".join(r["text"] for r in chunk)),
                    "math": max(r["math"] for r in chunk),
                    "nlines": k,
                })
        pages.append(wins)
    return pages


def locate_truth(truth: list[str], windows: list[list[dict]], doc_len: int,
                 threshold: float = 0.40) -> list[dict | None]:
    """Find the PDF window for each source formula, in document order.

    Uses visible-character similarity only. A monotonic page cursor keeps the
    document order, so a repeated symbol cannot jump to an earlier page.
    Never looks at OCR output -> weak recognition cannot corrupt alignment.
    """
    located: list[dict | None] = []
    cursor = 0
    used: set[tuple[int, tuple[float, ...]]] = set()
    for t in truth:
        q = visible(t)
        if len(q) < 6:
            located.append(None)
            continue
        best, best_score = None, 0.0
        # Search the whole document (a formula can sit on p7/p17 of a paper
        # whose earlier pages contain no display math). Monotonic cursor only
        # forbids going *backwards*, it does not cap how far ahead we look.
        for pno in range(cursor, doc_len):
            for w in windows[pno]:
                if not w["vis"]:
                    continue
                key = (w["page"], tuple(w["bbox"]))
                if key in used:
                    continue
                s = SequenceMatcher(None, q, w["vis"], autojunk=False).ratio()
                # prefer windows that are not much longer than the formula
                s *= min(1.0, (len(q) / max(1, len(w["vis"]))) ** 0.35)
                if w["math"] < 0.25:
                    s *= 0.85
                if s > best_score:
                    best, best_score = w, s
        if best is not None and best_score >= threshold:
            used.add((best["page"], tuple(best["bbox"])))
            located.append({**best, "align_conf": round(best_score, 2)})
            cursor = min(doc_len - 1, best["page"] - 1)
        else:
            located.append(None)
    return located


# --------------------------------------------------------------------------
# 5. Recognize crops and score
# --------------------------------------------------------------------------
def recognize(doc, boxes: list[dict], zoom: float, pad: float, engine) -> list[str]:
    out = []
    for b in boxes:
        page = doc[b["page"] - 1]
        x0, y0, x1, y1 = b["bbox"]
        clip = fitz.Rect(max(0, x0 - pad), max(0, y0 - pad),
                         min(page.rect.width, x1 + pad), min(page.rect.height, y1 + pad))
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=False)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3]
        try:
            latex, _ = engine(img)
            out.append(PL._tidy_latex(str(latex).strip()))
        except Exception as exc:  # keep the benchmark running
            out.append(f"[ERROR {type(exc).__name__}]")
    return out


def evaluate(arxiv_id: str, zoom: float, pad: float, engine, limit: int | None = None,
             verbose: bool = True) -> dict:
    name, main_tex = PAPERS[arxiv_id]
    truth = extract_truth(expand_source(arxiv_id, main_tex))
    doc = fitz.open(str(DATA / f"{arxiv_id}.pdf"))
    windows = page_windows(doc)
    located = locate_truth(truth, windows, len(doc))
    n_located = sum(1 for b in located if b is not None)
    items = [(i, b, truth[i]) for i, b in enumerate(located) if b is not None]
    if limit:
        items = items[:limit]
    boxes = [b for _, b, _ in items]
    preds = recognize(doc, boxes, zoom, pad, engine)
    results = []
    for (ti, b, _), pred in zip(items, preds):
        r = score_pair(truth[ti], pred)
        r.update({"arxiv_id": arxiv_id, "page": b["page"],
                  "align_conf": b["align_conf"], "box": b["bbox"]})
        results.append(r)
    doc.close()
    n = len(results)
    summary = {
        "arxiv_id": arxiv_id, "name": name,
        "truth_count": len(truth), "located": n_located, "scored": n,
        "locate_rate": round(n_located / max(1, len(truth)), 4),
        "zoom": zoom, "pad": pad,
        "exact": round(sum(r["exact"] for r in results) / n, 4) if n else 0,
        "f1": round(sum(r["f1"] for r in results) / n, 4) if n else 0,
        "sim": round(sum(r["sim"] for r in results) / n, 4) if n else 0,
        "ge90": round(sum(r["f1"] >= 0.90 for r in results) / n, 4) if n else 0,
    }
    if verbose:
        print(f"  {arxiv_id} {name[:32]:<32} truth={len(truth):>3} located={n_located:>3} "
              f"scored={n:>3} rate={summary['locate_rate']:.2f}  exact={summary['exact']:.3f}  "
              f"f1={summary['f1']:.3f}  sim={summary['sim']:.3f}  >=.90={summary['ge90']:.3f}")
    return {"summary": summary, "results": results}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", action="store_true", help="run the benchmark")
    ap.add_argument("--tune", action="store_true", help="zoom/pad parameter sweep")
    ap.add_argument("--zoom", type=float, default=2.0)
    ap.add_argument("--pad", type=float, default=2.0)
    ap.add_argument("--limit", type=int, default=None, help="max formulas per paper")
    ap.add_argument("--ids", nargs="*", default=list(PAPERS))
    ap.add_argument("--json", type=str, default=None)
    args = ap.parse_args()
    if not (args.eval or args.tune):
        ap.error("pass --eval or --tune")

    t0 = time.time()
    engine = LR.latex_engine()
    print(f"engine loaded in {time.time() - t0:.1f}s\n")

    if args.tune:
        configs = [(z, p) for z in (2.0, 3.0, 4.0) for p in (2.0, 5.0)]
        for zoom, pad in configs:
            print(f"=== zoom={zoom} pad={pad} ===")
            tot = []
            for aid in args.ids:
                r = evaluate(aid, zoom, pad, engine, limit=args.limit or 12)
                tot += r["results"]
            n = len(tot)
            if n:
                print(f"  OVERALL  n={n}  exact={sum(x['exact'] for x in tot)/n:.4f}  "
                      f"f1={sum(x['f1'] for x in tot)/n:.4f}  "
                      f"sim={sum(x['sim'] for x in tot)/n:.4f}  "
                      f">=.90={sum(x['f1']>=.9 for x in tot)/n:.4f}\n")
        return

    allres, summaries = [], []
    print(f"=== EVAL zoom={args.zoom} pad={args.pad} ===")
    for aid in args.ids:
        r = evaluate(aid, args.zoom, args.pad, engine, limit=args.limit)
        summaries.append(r["summary"])
        allres += r["results"]
    n = len(allres)
    if n:
        print(f"\nOVERALL  n={n}  exact={sum(x['exact'] for x in allres)/n:.4f}  "
              f"f1={sum(x['f1'] for x in allres)/n:.4f}  "
              f"sim={sum(x['sim'] for x in allres)/n:.4f}  "
              f">=.90={sum(x['f1']>=.9 for x in allres)/n:.4f}")
        worst = sorted(allres, key=lambda x: x["f1"])[:8]
        print("\nWORST CASES")
        for w in worst:
            print(f"  {w['arxiv_id']} p{w['page']} f1={w['f1']:.2f} conf={w['align_conf']}")
            print(f"    truth: {w['truth'][:110]}")
            print(f"    pred : {w['pred'][:110]}")
    print(f"\nelapsed {time.time() - t0:.1f}s")
    if args.json:
        Path(args.json).write_text(
            json.dumps({"summaries": summaries, "results": allres}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(f"wrote {args.json}")


if __name__ == "__main__":
    main()
