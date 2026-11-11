import fitz
import uuid
import re
from pathlib import Path
from config import settings


# Patterns for front-matter / non-substantive chapter titles
SKIP_TITLE_PATTERNS = [
    r'^(前言|导言|序言|序|目录|概观|符号|约定|术语|致谢|版权|许可)',
    r'^(Preface|Introduction|Contents|Notation|Convention|Acknowledg)',
    r'^(本|该|此|这|那|若|设|令|取|则|故|因|但|而|且|或|非)\s',  # Chinese conjunction/pronoun fragments
    r'^[0-9.]+\s*$',  # Pure numbers
    r'^[ivxlcdm]+$',  # Roman numerals
    r'^[\(\[\{].*[\)\]\}]$',  # Parenthesized fragments
    r'^.{,3}$',  # Very short (<4 chars)
]

# Threshold: how many consecutive short chapters trigger merging
SHORT_CHAPTER_THRESHOLD = 5


def _is_front_matter(title: str) -> bool:
    """Check if a chapter title indicates front matter or non-content."""
    for pat in SKIP_TITLE_PATTERNS:
        if re.search(pat, title):
            return True
    return False


def _is_body_chapter(title: str) -> bool:
    """Check if a chapter title looks like a real body chapter heading."""
    title_stripped = title.strip()
    # "第一章", "第1章", "Chapter 1", "§1"
    if re.search(r'第[一二三四五六七八九十\d]+章|第\s*\d+\s*章|Chapter\s+\d+|§\d+', title_stripped):
        return True
    # "1.1", "1.1.1" (subsection)
    if re.search(r'^\d+\.\d+', title_stripped):
        return True
    # "1. 群的概念" (numbered with dot-space, Chinese math convention)
    if re.search(r'^\d+\.\s+\S', title_stripped):
        return True
    # "1 群" (number then content, minimum 4 chars to avoid false positives)
    if re.search(r'^\d+\s+\S', title_stripped) and len(title_stripped) >= 4:
        return True
    # "一、群的定义" / "一 群" (Chinese numeral section)
    if re.search(r'^[一二三四五六七八九十]+[、，\s]\S', title_stripped):
        return True
    return False


def parse_pdf(filepath: str) -> list[dict]:
    """Parse PDF into structured chapters. Returns list of {id, title, content, index, is_frontmatter}."""
    doc = fitz.open(filepath)
    chapters = []
    current_chapter = None
    current_text = []
    chapter_idx = 0
    is_current_frontmatter = True  # Start as front matter until first body chapter

    # Get TOC for section titles
    toc = doc.get_toc(simple=True)
    toc_titles = set()
    toc_page_starts: dict[int, str] = {}
    for entry in toc:
        level, title, page = entry
        toc_titles.add(title.strip())
        toc_page_starts[page - 1] = title.strip()  # Convert to 0-indexed

    for page_num in range(len(doc)):
        page = doc[page_num]
        blocks = page.get_text("blocks")
        blocks.sort(key=lambda b: (b[1], b[0]))

        # Check if this page starts a TOC section
        if page_num in toc_page_starts:
            toc_title = toc_page_starts[page_num]
            if _is_body_chapter(toc_title):
                is_current_frontmatter = False
            elif _is_front_matter(toc_title):
                is_current_frontmatter = True

        for block in blocks:
            text = block[4].strip()
            if not text:
                continue

            # Chapter detection: short line that looks like a heading.
            # Must be a dedicated heading line, not just a random short text fragment.
            is_heading = False
            if len(text) < 120:
                # Explicit heading prefixes
                if any(text.startswith(w) for w in ["Chapter", "CHAPTER", "第", "§"]):
                    is_heading = True
                # Numbered section: "1.1", "1.2.3", "1. 群的概念", "1 群"
                elif text[0].isdigit():
                    is_heading = bool(re.match(
                        r'^\d+(?:\.\d+)*[\.\s]\s*\S',
                        text
                    ))
                # Chinese numeral section: "一、", "二、"
                elif re.match(r'^[一二三四五六七八九十]+[、，\s]\S', text):
                    is_heading = True
                # ALL CAPS title (math convention): "GROUPS AND RINGS", minimum 6 chars
                elif text.upper() == text and len(text) >= 6 and not re.search(r'[^A-Z\s]', text):
                    is_heading = True

            # Also detect TOC section titles as headings
            if not is_heading and text in toc_titles:
                is_heading = True

            if is_heading:
                # Check if this heading changes front/body matter
                if _is_body_chapter(text):
                    is_current_frontmatter = False

                if current_chapter and current_text:
                    chapter_content = "\n".join(current_text)
                    chapters.append({
                        "id": current_chapter["id"],
                        "title": current_chapter["title"],
                        "content": chapter_content,
                        "index": current_chapter["index"],
                        "is_frontmatter": current_chapter["is_frontmatter"],
                    })
                chapter_idx += 1
                current_chapter = {
                    "id": str(uuid.uuid4()),
                    "title": text,
                    "index": chapter_idx,
                    "is_frontmatter": is_current_frontmatter,
                }
                current_text = []
            else:
                if current_chapter is None:
                    current_chapter = {
                        "id": str(uuid.uuid4()),
                        "title": "Introduction",
                        "index": 0,
                        "is_frontmatter": True,
                    }
                    chapter_idx = 1
                current_text.append(text)

    if current_chapter and current_text:
        chapters.append({
            "id": current_chapter["id"],
            "title": current_chapter["title"],
            "content": "\n".join(current_text),
            "index": current_chapter["index"],
            "is_frontmatter": current_chapter["is_frontmatter"],
        })

    if not chapters:
        full_text = ""
        for page in doc:
            full_text += page.get_text()
        chapters.append({
            "id": str(uuid.uuid4()),
            "title": "Full Text",
            "content": full_text,
            "index": 0,
            "is_frontmatter": False,
        })

    doc.close()

    # Merge: 2674 tiny chapters is useless. Group very short chapters together.
    merged = _merge_short_chapters(chapters)

    return merged


def _merge_short_chapters(chapters: list[dict]) -> list[dict]:
    """Merge consecutive very short chapters into larger ones."""
    # Merging benefits all books: even small books can have fragmented chapters.
    if len(chapters) < 3:
        return chapters

    merged = []
    buffer_title = ""
    buffer_text = []
    buffer_id = ""
    buffer_index = 0
    buffer_frontmatter = True

    for ch in chapters:
        is_short = len(ch["content"]) < 200

        if is_short:
            # Merge into buffer
            if not buffer_text:
                buffer_id = ch["id"]
                buffer_index = ch["index"]
                buffer_frontmatter = ch["is_frontmatter"]
            buffer_title = (buffer_title or ch["title"])
            buffer_text.append(ch["content"])
        else:
            # Flush buffer first
            if buffer_text:
                merged.append({
                    "id": buffer_id,
                    "title": buffer_title or "Merged Section",
                    "content": "\n\n".join(buffer_text),
                    "index": buffer_index,
                    "is_frontmatter": buffer_frontmatter,
                })
                buffer_text = []
                buffer_title = ""
            merged.append(ch)

    if buffer_text:
        merged.append({
            "id": buffer_id,
            "title": buffer_title or "Merged Section",
            "content": "\n\n".join(buffer_text),
            "index": buffer_index,
            "is_frontmatter": buffer_frontmatter,
        })

    return merged


def detect_language(text: str) -> str:
    """Detect if text is primarily Chinese or English."""
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    total_chars = len(text.replace(' ', '').replace('\n', ''))
    if total_chars == 0:
        return "en"
    return "zh" if chinese_chars / total_chars > 0.15 else "en"


def chunk_text(text: str, max_chars: int = 3000) -> list[str]:
    """Chunk text into manageable pieces for LLM processing."""
    paragraphs = text.split('\n\n')
    chunks = []
    current = ""

    for para in paragraphs:
        if len(current) + len(para) > max_chars and current:
            chunks.append(current.strip())
            current = para
        else:
            current += "\n\n" + para if current else para

    if current.strip():
        chunks.append(current.strip())

    return chunks
