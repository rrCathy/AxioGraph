"""Inspect chapter structure of the Chinese topology book."""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r'C:\newproject\AxioGraph\backend')
sys.path.insert(0, '.')
from parser import parse_pdf

chapters = parse_pdf(r'C:\newproject\AxioGraph\tests\代数拓扑.pdf')

print(f'Total chapters: {len(chapters)}')
print()

print('=== BODY chapters (>300 chars) ===')
for ch in chapters:
    if not ch.get('is_frontmatter') and len(ch.get('content','')) > 300:
        print(f'  [{ch["index"]}] title={ch["title"][:80]}  ({len(ch["content"])} chars)')
        print(f'    content[:200]: {ch["content"][:200]}')
        print()

print('=== FRONTMATTER chapters (>500 chars) ===')
count = 0
for ch in chapters:
    if ch.get('is_frontmatter') and len(ch.get('content','')) > 500:
        count += 1
        if count <= 10:
            print(f'  [{ch["index"]}] title={ch["title"][:80]}  ({len(ch["content"])} chars)')
            print(f'    content[:200]: {ch["content"][:200]}')
            print()
print(f'Total frontmatter with >500 chars: {count}')
