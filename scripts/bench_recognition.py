"""Recognition benchmark for a reference book.

There is no trainable model in this project (all weights are frozen ONNX
models), so "training" here means: use a clean book as a repeatable benchmark,
measure several independent accuracy dimensions, and locate the worst pages
to improve the pipeline.

Metrics
  han_recall    share of reference Han characters that survive in layout_text
  han_order     ordered similarity of the Han character sequence
  formula_cov   share of detected formula blocks that carry valid LaTeX
  garbage       count of obvious TeX/OCR artifact patterns
  usable        han_recall >= 0.98 and no garbage

Run from backend/:  python ../scripts/bench_recognition.py [book_id] [pages]
"""
import re
import sys
import time
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

import pymupdf as fitz
from page_service import pdf_path, text_quality
import page_layout as PL

BOOK = sys.argv[1] if len(sys.argv) > 1 else 'e9057a2f-52aa-4c04-bc04-a0aa430dbbd7'
SAMPLE = [1, 7, 18, 30, 50, 80, 103, 130, 160, 200, 230, 265, 300, 341, 380, 410, 430]
if len(sys.argv) > 2:
    SAMPLE = [int(x) for x in sys.argv[2].split(',')]

HAN = re.compile(r'[\u4e00-\u9fff]')
GARBAGE = re.compile(r'(?:\u221a\s*){3,}|\b9P\(|\b33P|(?:\\[a-zA-Z]+\s*){25,}')


def han(text):
    return HAN.findall(text or '')


def metrics(ref, pred, layout):
    ft, fr = layout.get('formula_total') or 0, layout.get('formula_recognized') or 0
    cov = fr / ft if ft else None
    garbage = len(GARBAGE.findall(pred or ''))
    # Running headers / page numbers are deliberately excluded by the layout
    # pipeline (NOISE blocks). Remove them from the reference too; otherwise
    # correct behaviour is scored as character loss.
    noise = ' '.join(b.get('text') or '' for b in layout.get('blocks') or []
                     if b.get('type') == 'NOISE')
    rc = Counter(han(ref))
    for c, n in Counter(han(noise)).items():
        rc[c] = max(0, rc[c] - n)
    pc = Counter(han(pred))
    # Keep the ORIGINAL character order; only drop the noise occurrences.
    drop = Counter(han(noise))
    r = []
    for c in han(ref):
        if drop[c]:
            drop[c] -= 1
        else:
            r.append(c)
    p = han(pred)
    # Blank / image-only pages have no reference characters: perfect, not 0%.
    if not r:
        return 1.0, 1.0, cov, garbage, ft
    recall = sum(min(rc[c], pc[c]) for c in rc) / len(r)
    order = SequenceMatcher(None, r, p, autojunk=False).ratio()
    return recall, order, cov, garbage, ft


def main():
    doc = fitz.open(str(pdf_path(BOOK)))
    rows = []
    print('page\thans\trecall\torder\tformulas\tcov\tgarbage\ts')
    for pno in SAMPLE:
        if pno > len(doc):
            continue
        t0 = time.time()
        ref = doc[pno - 1].get_text('text')
        layout = PL.build_layout(BOOK, pno)
        _, pred = PL.to_storage(layout)
        recall, order, cov, garbage, ft = metrics(ref, pred, layout)
        dt = round(time.time() - t0, 1)
        rows.append((pno, recall, order, cov, garbage, ft))
        print(f'{pno}\t{len(han(ref))}\t{recall:.3f}\t{order:.3f}\t{ft}\t'
              f'{cov if cov is not None else "-":}\t{garbage}\t{dt}')
    doc.close()

    n = len(rows)
    recalls = [r[1] for r in rows]
    orders = [r[2] for r in rows]
    covs = [r[3] for r in rows if r[3] is not None]
    usable = sum(1 for r in rows if r[1] >= 0.98 and r[4] == 0)
    print('\n=== SUMMARY ===')
    print('pages sampled      ', n)
    print('mean han_recall    ', round(sum(recalls) / n, 4))
    print('mean han_order     ', round(sum(orders) / n, 4))
    print('min han_recall     ', round(min(recalls), 4))
    print('formula coverage   ', round(sum(covs) / len(covs), 4) if covs else 'n/a',
          f'({len(covs)} pages with formulas)')
    print('usable pages       ', usable, '/', n, '=', round(usable / n, 4))
    worst = sorted(rows, key=lambda r: r[1])[:5]
    print('worst pages        ', [(r[0], round(r[1], 3), r[5]) for r in worst])


if __name__ == '__main__':
    main()
