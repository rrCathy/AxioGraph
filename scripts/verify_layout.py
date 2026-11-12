"""Acceptance: before/after numbers for the three screenshot pages.

Run: cd backend && python ../scripts/verify_layout.py
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from database import init_db, get_db  # noqa: E402
import page_layout as L  # noqa: E402
import page_service as ps  # noqa: E402
import page_extractor as pe  # noqa: E402

init_db()

CASES = [
    ("① 目录页 位置/层级", "7559b406-59fb-41cd-81f6-42a7e96a78e2", 3),
    ("② 示意图 选择性提取", "7559b406-59fb-41cd-81f6-42a7e96a78e2", 14),
    ("③ 三公式 拎成节点", "a0eae8c3-916d-4ca7-a36f-a0bd38cd6617", 24),
]

# Ensure caches are rebuilt with the current schema (formula_name_map etc.).
for _book in {c[1] for c in CASES}:
    ps.clear_layout(_book)


def main():
    conn0 = sqlite3.connect(str(ROOT / "data" / "axiograph.db"))
    for tag, book, pn in CASES:
        row = conn0.execute(
            "SELECT text_raw FROM pages WHERE book_id=? AND page_no=?", (book, pn)
        ).fetchone()
        old = row[0] or ""
        d = L.build_layout(book, pn)
        new = L.render_layout_text(d)
        print("=" * 76)
        print(f"{tag}  book={book[:8]} p{pn}")
        print(f"  BEFORE: {len(old)} chars / {len(old.splitlines())} flat lines | head={old[:52]!r}")
        print(f"  AFTER : {len(new)} chars / {len(d['blocks'])} typed blocks | counts={d['counts']}")
        print(f"          kind={d['page_kind']} needs_vision={d['needs_vision']} "
              f"figure_boxes={len(d['figure_boxes'])} formula_numbers={d['formula_numbers']}")
        for b in d["blocks"][:4]:
            print(f"          [{b['type']}] {b['text'][:66]}")
        # selective extraction: figure labels must NOT appear in LLM input
        leaked = [lab for lab in d["figure_labels"] if lab and lab in new]
        print(f"  figure labels excluded from LLM input: "
              f"{len(d['figure_labels'])} labels, {len(leaked)} leaked")
        # formula candidates (transaction rolled back — no data pollution)
        conn = get_db()
        try:
            saved = pe._formula_candidates(conn, book, pn, pn)
            print(f"  FORMULA pending candidates: {len(saved)}")
            for s in saved[:6]:
                print(f"          - {s['name']}")
        finally:
            conn.rollback()
            conn.close()
    conn0.close()
    print("=" * 76)


if __name__ == "__main__":
    main()
