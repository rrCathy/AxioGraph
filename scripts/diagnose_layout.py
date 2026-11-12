"""Read-only layout diagnosis for the three pages the user screenshotted.

Quantifies: what the current text layer keeps, what span-level geometry knows,
whether pymupdf4llm can restore hierarchy/reading order, whether vector
drawings can delimit schematic figures, and where formulas disappeared.
"""
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import pymupdf as fitz

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "axiograph.db"
CASES = [
    ("图1 目录页", "7559b406-59fb-41cd-81f6-42a7e96a78e2", 3),
    ("图2 示意图页", "7559b406-59fb-41cd-81f6-42a7e96a78e2", 14),
    ("图3 三公式页", "a0eae8c3-916d-4ca7-a36f-a0bd38cd6617", 24),
]


def spans_of(page):
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for s in line.get("spans", []):
                if s["text"].strip():
                    out.append(s)
    return out


def closed_rects(page):
    rects = []
    for d in page.get_drawings():
        for item in d["items"]:
            if item[0] == "re":
                r = fitz.Rect(item[1])
                if r.width > 25 and r.height > 25:
                    rects.append((r, d.get("fill") is not None))
            elif item[0] == "l":  # line
                pass
    return rects


def main():
    conn = sqlite3.connect(str(DB))
    for label, book_id, page_no in CASES:
        path = ROOT / "data" / "books" / f"{book_id}.pdf"
        doc = fitz.open(str(path))
        page = doc[page_no - 1]
        raw = conn.execute(
            "SELECT text_raw FROM pages WHERE book_id=? AND page_no=?",
            (book_id, page_no),
        ).fetchone()[0] or ""
        spans = spans_of(page)
        sizes = Counter(round(s["size"], 1) for s in spans)
        bold = sum(1 for s in spans if s["flags"] & 2 ** 4)
        print("=" * 74)
        print(f"{label}  book={book_id[:8]} p{page_no}  page={page.rect.width:.0f}x{page.rect.height:.0f}pt")
        print(f"current pages.text_raw: {len(raw)} chars, {len(raw.splitlines())} lines")
        print("  first 220 chars:", repr(raw[:220]))

        print(f"span-level geometry: {len(spans)} spans | sizes={dict(sizes.most_common(6))} | bold={bold}")
        # y-position histogram: column/heading detection feasibility
        ys = sorted(round(s["bbox"][1] / 50) * 50 for s in spans)
        print(f"  y-bands(50pt): {dict(Counter(ys).most_common(6))}")

        rects = closed_rects(page)
        print(f"vector rects(>25pt): {len(rects)} -> {[tuple(round(v) for v in r) for r, _ in rects[:6]]}")
        if rects:
            inside = []
            for s in spans:
                c = fitz.Point((s["bbox"][0] + s["bbox"][2]) / 2,
                               (s["bbox"][1] + s["bbox"][3]) / 2)
                if any(r.contains(c) for r, _ in rects):
                    inside.append(s["text"].strip())
            print(f"  spans INSIDE those rects ({len(inside)}): {inside[:22]}")

        try:
            import pymupdf4llm
            md = pymupdf4llm.to_markdown(doc, pages=[page_no - 1])
            print(f"pymupdf4llm markdown: {len(md)} chars")
            print("  --- md head ---")
            for line in md.splitlines()[:22]:
                print("   ", line[:100])
        except Exception as e:
            print("pymupdf4llm FAILED:", type(e).__name__, str(e)[:120])

        # formula-number anchors
        import re
        nums = re.findall(r"\(\s*1\.[5-8]\s*\)", raw)
        print(f"formula-number anchors (1.5)-(1.8) in current text: {nums}")
        doc.close()
    conn.close()


if __name__ == "__main__":
    sys.exit(main())
