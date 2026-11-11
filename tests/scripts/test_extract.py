import sys, os, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir('C:/newproject/AxioGraph/backend')
sys.path.insert(0, '.')

from parser import parse_pdf, chunk_text, detect_language
from extractor import extract_from_text

# Parse the Serre book
pdf_path = r"C:\newproject\AxioGraph\tests\有限群的线性表示-Jean-Pierre Serre.pdf"
chapters = parse_pdf(pdf_path)
print(f"Total chapters: {len(chapters)}")

# Find body chapters with content
body = [ch for ch in chapters if not ch.get("is_frontmatter", False)]
print(f"Body chapters: {len(body)}")

# Test extraction on first body chapter (small chunks)
for ch in body[:2]:
    title = ch.get("title", "?")
    text = ch.get("content", "")
    chunks = chunk_text(text, max_chars=2000)
    print(f"\n=== Chapter: {title[:60]} ({len(text)} chars, {len(chunks)} chunks) ===")
    
    for ci, chunk_text_val in enumerate(chunks[:2]):  # Only first 2 chunks
        if len(chunk_text_val.strip()) < 100:
            continue
        print(f"  Chunk {ci} ({len(chunk_text_val)} chars)...")
        try:
            results = extract_from_text(chunk_text_val, section=title[:80])
            print(f"    Found {len(results)} entities")
            for r in results[:3]:
                e = r.get("entity", {})
                rels = r.get("relations", [])
                print(f"    [{e.get('type','?')}] {e.get('name','?')[:60]}")
                for rel in rels:
                    print(f"      -> {rel.get('type','?')} {rel.get('target','?')[:40]}")
        except Exception as e:
            print(f"    Error: {e}")

print("\nDone!")
