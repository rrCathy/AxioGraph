#!/usr/bin/env python3
"""Chinese-textbook formula benchmark with the author's own LaTeX as truth.

The AlJabr-1 repository ships both `Al-jabr-1.pdf` and the chapter .tex files
of the SAME compile, so display formulas are human-written ground truth -- no
transcription needed. This complements the existing three tiers:

  bench_recognition.py  Chinese book   Han characters (PDF text layer as truth)
  bench_formula.py      arXiv papers   formula semantics, English, 37 items
  bench_im2latex.py     engine only    clean formula crops, no localization
  bench_aljabr.py       THIS           formula semantics + diagrams in a real
                                       Chinese math book (XeLaTeX + xeCJK)

Localization uses only the PDF text layer (never OCR output), so a weak
recognizer cannot make the alignment look better. LaTeX commands are mapped to
the Unicode glyphs XeLaTeX actually writes before comparing.

Setup (once):
  curl -L -o data/bench_aljabr/src.tar.gz \
    https://codeload.github.com/wenweili/AlJabr-1/tar.gz/refs/heads/master
  tar -xzf data/bench_aljabr/src.tar.gz -C data/bench_aljabr

Usage:
  python scripts/bench_aljabr.py --limit 40
  python scripts/bench_aljabr.py --limit 120 --json data/bench_aljabr/result.json

NOTE: the repository PDF (445 pp, 2026-01-13) is NOT the same build as the PDF
imported in the workbench (443 pp). Use the repository PDF here; do not try to
align source page numbers against the workbench copy.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))
import pymupdf as fitz  # noqa: E402
import page_layout as L  # noqa: E402
import bench_formula as BF  # noqa: E402

SRC = ROOT / "data" / "bench_aljabr" / "AlJabr-1-master"
PDF = SRC / "Al-jabr-1.pdf"

# XeLaTeX writes real Unicode into the text layer; the .tex source uses commands.
CMD = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "varepsilon": "ε", "zeta": "ζ", "eta": "η", "theta": "θ", "iota": "ι",
    "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π",
    "rho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ", "phi": "φ",
    "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ",
    "Pi": "Π", "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
    "to": "→", "rightarrow": "→", "longrightarrow": "→", "leftarrow": "←",
    "mapsto": "↦", "Rightarrow": "⇒", "Leftrightarrow": "⇔", "leftrightarrow": "↔",
    "times": "×", "circ": "∘", "cdot": "·", "simeq": "≃", "cong": "≅",
    "sim": "∼", "approx": "≈", "equiv": "≡", "neq": "≠", "ne": "≠",
    "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "ll": "≪", "gg": "≫",
    "in": "∈", "notin": "∉", "subset": "⊂", "supset": "⊃", "subseteq": "⊆",
    "supseteq": "⊇", "cup": "∪", "cap": "∩", "emptyset": "∅", "varnothing": "∅",
    "infty": "∞", "partial": "∂", "nabla": "∇", "forall": "∀", "exists": "∃",
    "sum": "∑", "prod": "∏", "int": "∫", "oint": "∮", "sqrt": "√",
    "wedge": "∧", "vee": "∨", "oplus": "⊕", "otimes": "⊗", "perp": "⊥",
    "ell": "ℓ", "hbar": "ℏ", "prime": "′", "dots": "…", "ldots": "…",
    "cdots": "⋯", "quad": " ", "qquad": " ", "langle": "⟨", "rangle": "⟩",
    "mathrm": "", "mathbf": "", "mathcal": "", "mathbb": "", "mathsf": "",
    "mathfrak": "", "operatorname": "", "text": "", "textbf": "", "bm": "",
    "left": "", "right": "", "big": "", "Big": "", "bigg": "", "Bigg": "",
    "limits": "", "displaystyle": "", "nolimits": "", "tag": "", "label": "",
}
_DROP = re.compile(r"\\(?:begin|end)\{[a-zA-Z*]+\}|\\(?:label|tag|nonumber|notag)\{[^{}]*\}|"
                   r"\\[,;:! ]|\\(?:quad|qquad)")
_KEEP = re.compile(
    r"[^0-9A-Za-z\u4e00-\u9fff=+*/().,<>|→←↦⇒⇔↔×∘·≃≅∼≈≡≠≤≥≪≫"
    r"∈∉⊂⊃⊆⊇∪∩∅∞∂∇∀∃∑∏∫∮√∧∨⊕⊗⊥ℓℏ′…⋯]")
_FONT = re.compile(
    r"\\(?:mathcal|mathbf|mathbb|mathrm|mathsf|mathfrak|operatorname\*?|text|textbf|bm)"
    r"\s*\{([^{}]*)\}")


def visible(s: str) -> str:
    """Source LaTeX -> the character stream the XeLaTeX PDF text layer has."""
    s = re.sub(r"(?m)(?<!\\)%.*$", "", s)
    s = _DROP.sub(" ", s)
    for _ in range(3):
        s = _FONT.sub(r"\1", s)
    s = re.sub(r"\\([a-zA-Z]+)", lambda m: CMD.get(m.group(1), ""), s)
    s = s.replace("&", "").replace("\\\\", "").replace("{", "").replace("}", "")
    s = re.sub(r"[\^_]", "", s)
    return _KEEP.sub("", s)


ENV_RE = re.compile(
    r"\\begin\{(equation\*?|align\*?|gather\*?|multline\*?|eqnarray\*?|displaymath)\}"
    r"(.*?)\\end\{\1\}", re.S)
CD_RE = re.compile(r"\\begin\{tikzcd\}(.*?)\\end\{tikzcd\}", re.S)
ARROW_RE = re.compile(r"\\arrow\s*\[([^\]]*)\]")


def load_truth():
    formulas, diagrams = [], []
    files = sorted(SRC.glob("chapter*.tex"),
                   key=lambda p: int(re.search(r"\d+", p.name).group()))
    for f in files:
        s = f.read_text(encoding="utf-8", errors="replace")
        for m in ENV_RE.finditer(s):
            body = m.group(2).strip()
            if "\\begin{tikzcd}" in body:
                # counted once by CD_RE below, whether standalone or wrapped
                continue
            v = visible(body)
            if len(v) >= 8:
                formulas.append({"chapter": f.stem, "env": m.group(1),
                                 "body": body, "visible": v,
                                 "has_han": bool(re.search(r"[\u4e00-\u9fff]", body))})
        for m in CD_RE.finditer(s):
            diagrams.append({"chapter": f.stem, "arrows": len(ARROW_RE.findall(m.group(1)))})
    return formulas, diagrams


def build_windows(doc):
    out = []
    for pno in range(1, len(doc) + 1):
        lines = [l.strip() for l in doc[pno - 1].get_text("text").splitlines() if l.strip()]
        for i in range(len(lines)):
            for span in (1, 2, 3, 5):
                w = visible(" ".join(lines[i:i + span]))
                if len(w) >= 8:
                    out.append((pno, w))
    return out


def locate(truths, windows, threshold, budget):
    """Return (located, scanned). `budget` caps successful hits, not the
    number of candidates examined -- the reported rate must stay honest."""
    cursor, out, scanned = 0, [], 0
    for t in truths:
        if len(out) >= budget:
            break
        scanned += 1
        best, score = None, 0.0
        for i in range(max(0, cursor - 800), min(len(windows), cursor + 12000)):
            pno, w = windows[i]
            if abs(len(w) - len(t["visible"])) > 3 * max(1, len(t["visible"])):
                continue
            sm = SequenceMatcher(None, t["visible"], w, autojunk=False)
            if sm.quick_ratio() < threshold:
                continue
            sc = sm.ratio()
            if sc > score:
                score, best = sc, (i, pno)
        if best and score >= threshold:
            cursor = best[0] + 1
            out.append({**t, "page": best[1], "align_conf": round(score, 3)})
    return out, scanned


def normalize(s: str) -> str:
    """Collapse spellings that are semantically identical BEFORE canon().
    Applied to BOTH truth and prediction, so it cannot inflate the score by
    weakening only one side. Records the AlJabr-1 macro vocab explicitly."""
    s = re.sub(r"\\xrightarrow\s*\{([^{}]*)\}", r"\\ARROW{\1}", s)
    s = re.sub(r"\\xleftarrow\s*\{([^{}]*)\}", r"\\LARROW{\1}", s)
    s = re.sub(r"\\stackrel\s*\{([^{}]*)\}\s*\{\\longrightarrow\}", r"\\ARROW{\1}", s)
    s = re.sub(r"\\stackrel\s*\{([^{}]*)\}\s*\{\\longleftarrow\}", r"\\LARROW{\1}", s)
    s = re.sub(r"\\Obj\b", r"\\operatorname{Ob}", s)
    s = re.sub(r"\\bf(?=[A-Za-z0-9])", r"\\mathbf ", s)
    s = re.sub(r"\\identity_([A-Za-z])", r"\\mathrm{id}_{\1}", s)
    return s


def score(a: str, b: str) -> tuple[float, float]:
    """(raw f1, normalized f1) -- report both so a scoring change is visible."""
    return (BF.score_pair(a, b)["f1"],
            BF.score_pair(normalize(a), normalize(b))["f1"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40, help="max located formulas to score")
    ap.add_argument("--threshold", type=float, default=0.55)
    ap.add_argument("--json", type=str, default=None)
    args = ap.parse_args()

    if not PDF.exists():
        print(f"missing {PDF}; see the setup note in this file's docstring")
        return 1
    t0 = time.time()
    formulas, diagrams = load_truth()
    doc = fitz.open(str(PDF))
    print(f"source: {len(formulas)} display formulas, {len(diagrams)} tikzcd diagrams "
          f"(avg arrows {sum(d['arrows'] for d in diagrams)/max(1,len(diagrams)):.1f})")
    print(f"pdf: {len(doc)} pages", flush=True)
    windows = build_windows(doc)
    located, scanned = locate(formulas, windows, args.threshold, args.limit * 2)
    print(f"located {len(located)} of {scanned} scanned source formulas "
          f"({len(located)/max(1,scanned):.3f}); source total {len(formulas)} "
          f"in {time.time()-t0:.0f}s", flush=True)
    doc.close()

    by_page = defaultdict(list)
    for t in located[:args.limit]:
        by_page[t["page"]].append(t)
    results, pages_with_diagram, relations = [], 0, 0
    for k, (pno, ts) in enumerate(sorted(by_page.items()), 1):
        lay = L.build_layout("bench-aljabr", pno, pdf_override=str(PDF))
        preds = [b["latex"] for b in lay["blocks"]
                 if b["type"] == "FORMULA" and b.get("latex")]
        diags = [b for b in lay["blocks"] if b["type"] == "DIAGRAM"]
        pages_with_diagram += int(bool(diags))
        relations += sum(len(b.get("relations") or []) for b in diags)
        # Greedy one-to-one matching by token F1. A source align/gather often
        # becomes several adjacent FORMULA blocks; offer their concatenation
        # as an extra candidate with a private (non-conflicting) pred index.
        pairs = []
        multi = "\\\\".join(preds)
        for ti, t in enumerate(ts):
            for pi, p in enumerate(preds):
                raw, norm = score(t["body"], p)
                pairs.append((norm, raw, ti, pi))
            if t["env"].startswith(("align", "gather", "multline")) and len(preds) > 1:
                raw, norm = score(t["body"], multi)
                pairs.append((norm, raw, ti, -1 - ti))
        pairs.sort()
        used_t, used_p = set(), set()
        for norm, raw, ti, pi in reversed(pairs):
            if ti in used_t or pi in used_p:
                continue
            used_t.add(ti); used_p.add(pi)
            results.append({"page": pno, "env": ts[ti]["env"], "f1": norm,
                            "f1_raw": raw, "align_conf": ts[ti]["align_conf"],
                            "has_han": ts[ti]["has_han"]})
        if k % 10 == 0:
            print(f"  {k}/{len(by_page)} pages, scored={len(results)} "
                  f"{time.time()-t0:.0f}s", flush=True)

    f1s = [r["f1"] for r in results]
    by_env = defaultdict(list)
    for r in results:
        by_env[r["env"]].append(r["f1"])
    print("\n=== SUMMARY ===")
    attempted = located[:args.limit]
    print(f"pages processed     {len(by_page)}")
    print(f"located / attempted / scored   {len(located)} / {len(attempted)} / {len(results)} "
          f"(scored {len(results)/max(1,len(attempted)):.3f} of attempted)")
    raws = [r["f1_raw"] for r in results]
    print(f"mean token F1       {sum(f1s)/max(1,len(f1s)):.4f} "
          f"(normalized; raw same-side scoring {sum(raws)/max(1,len(raws)):.4f})")
    print(f">=0.90              {sum(x >= .9 for x in f1s)}/{len(f1s)}")
    print(f"pages with DIAGRAM  {pages_with_diagram}; extracted arrow relations {relations}")
    for env, vals in sorted(by_env.items()):
        print(f"  {env:<12} n={len(vals):<3} f1={sum(vals)/len(vals):.4f}")
    for tag, want in (("with Han \\text", True), ("pure symbols", False)):
        v = [r["f1"] for r in results if r["has_han"] == want]
        if v:
            print(f"  {tag:<16} n={len(v):<3} f1={sum(v)/len(v):.4f}")
    print(f"elapsed {time.time()-t0:.0f}s")
    if args.json:
        Path(args.json).write_text(
            json.dumps({"located": located[:args.limit], "results": results,
                        "diagrams": diagrams}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
