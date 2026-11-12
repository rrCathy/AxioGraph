"""Read-only: verify use_ocr=False markdown quality + vector-drawing figure detection."""
import pathlib
import sqlite3
import sys

import pymupdf as fitz

ROOT = pathlib.Path(__file__).resolve().parent.parent
CASES = [
    ("图1 目录", "7559b406-59fb-41cd-81f6-42a7e96a78e2", 3),
    ("图2 示意图", "7559b406-59fb-41cd-81f6-42a7e96a78e2", 14),
    ("图3 公式", "a0eae8c3-916d-4ca7-a36f-a0bd38cd6617", 24),
]


def drawing_boxes(page):
    boxes = []
    for d in page.get_drawings():
        r = fitz.Rect(d["rect"])
        lines = sum(1 for it in d["items"] if it[0] == "l")
        rects = sum(1 for it in d["items"] if it[0] == "re")
        if r.width > 15 and r.height > 15:
            boxes.append((r, lines, rects, len(d["items"])))
    return boxes


def spans_of(page):
    out = []
    for b in page.get_text("dict")["blocks"]:
        for line in b.get("lines", []):
            for s in line.get("spans", []):
                if s["text"].strip():
                    out.append(s)
    return out


def main():
    conn = sqlite3.connect(str(ROOT / "data" / "axiograph.db"))
    import pymupdf4llm
    for label, book_id, page_no in CASES:
        doc = fitz.open(str(ROOT / "data" / "books" / f"{book_id}.pdf"))
        page = doc[page_no - 1]
        md = pymupdf4llm.to_markdown(doc, pages=[page_no - 1], use_ocr=False)
        print("=" * 70)
        print(f"{label} p{page_no}: markdown {len(md)} chars (use_ocr=False)")
        for line in md.splitlines()[:14]:
            print("   ", line[:96])

        boxes = drawing_boxes(page)
        print(f"  vector drawing groups(>15pt): {len(boxes)}")
        for r, lines, rects, n in boxes[:8]:
            print(f"    rect={tuple(round(v) for v in r)} lines={lines} rect-items={rects} items={n}")
        big = [r for r, lines, rects, n in boxes if r.width > 40 and r.height > 40]
        if big:
            inside = []
            for s in spans_of(page):
                c = fitz.Point((s["bbox"][0] + s["bbox"][2]) / 2,
                               (s["bbox"][1] + s["bbox"][3]) / 2)
                if any(r.contains(c) for r in big):
                    inside.append(s["text"].strip())
            print(f"  spans inside big drawing boxes ({len(inside)}): {inside[:28]}")
        # formula-adjacent lines in markdown / raw
        raw = conn.execute("SELECT text_raw FROM pages WHERE book_id=? AND page_no=?",
                           (book_id, page_no)).fetchone()[0] or ""
        import re
        anchors = re.findall(r"\(\s*1\.\s*[5-8]\s*\)|\(\s*0\.7\s*\)", raw)
        print(f"  raw formula-number anchors: {anchors}")
        print(f"  markdown has 'Green': {'Green' in md}, 'Stokes': {'Stokes' in md}, 'Gauss': {'Gauss' in md}")
        doc.close()
    conn.close()


if __name__ == "__main__":
    sys.exit(main())
