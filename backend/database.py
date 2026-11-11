import sqlite3
from config import settings


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.sqlite_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS books (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            filename TEXT NOT NULL,
            language TEXT DEFAULT 'en',
            status TEXT DEFAULT 'pending',
            progress INTEGER DEFAULT 0,
            node_count INTEGER DEFAULT 0,
            edge_count INTEGER DEFAULT 0,
            chunk_total INTEGER DEFAULT 0,
            chunk_done INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS chapters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id TEXT NOT NULL,
            title TEXT,
            index_num INTEGER,
            content TEXT,
            FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS graph_nodes (
            id TEXT PRIMARY KEY,
            book_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            name TEXT NOT NULL,
            content TEXT,
            chapter TEXT,
            metadata TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS graph_edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            description TEXT,
            book_id TEXT,
            FOREIGN KEY (source_id) REFERENCES graph_nodes(id) ON DELETE CASCADE,
            FOREIGN KEY (target_id) REFERENCES graph_nodes(id) ON DELETE CASCADE,
            FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS pages (
            book_id TEXT NOT NULL,
            page_no INTEGER NOT NULL,
            text_raw TEXT,
            text_corrected TEXT,
            blocks_json TEXT DEFAULT '[]',
            char_count INTEGER DEFAULT 0,
            quality REAL DEFAULT 0,
            status TEXT DEFAULT 'pending',
            ocr_confidence REAL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (book_id, page_no),
            FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS candidates (
            id TEXT PRIMARY KEY,
            book_id TEXT NOT NULL,
            page_start INTEGER NOT NULL,
            page_end INTEGER NOT NULL,
            entity_type TEXT NOT NULL,
            name TEXT NOT NULL,
            content TEXT,
            quote TEXT,
            relations_json TEXT DEFAULT '[]',
            status TEXT DEFAULT 'pending',
            merged_into TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_nodes_book ON graph_nodes(book_id);
        CREATE INDEX IF NOT EXISTS idx_nodes_type ON graph_nodes(entity_type);
        CREATE INDEX IF NOT EXISTS idx_edges_source ON graph_edges(source_id);
        CREATE INDEX IF NOT EXISTS idx_edges_target ON graph_edges(target_id);
        CREATE INDEX IF NOT EXISTS idx_pages_book ON pages(book_id);
        CREATE INDEX IF NOT EXISTS idx_candidates_book ON candidates(book_id, status);
    """)
    # Migrate existing databases
    for col, col_type in [
        ("progress", "INTEGER DEFAULT 0"),
        ("node_count", "INTEGER DEFAULT 0"),
        ("edge_count", "INTEGER DEFAULT 0"),
        ("chunk_total", "INTEGER DEFAULT 0"),
        ("chunk_done", "INTEGER DEFAULT 0"),
    ]:
        try:
            conn.execute(f"ALTER TABLE books ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass

    # Page-level workflow: provenance + human review on existing graph tables.
    # Old rows default to 'legacy' so they can be filtered out, not deleted.
    for table, cols in [
        ("graph_nodes", [
            ("page_start", "INTEGER"),
            ("page_end", "INTEGER"),
            ("review_status", "TEXT DEFAULT 'legacy'"),
            ("source_quote", "TEXT"),
            ("created_by", "TEXT DEFAULT 'ai'"),
            ("merged_into", "TEXT"),
        ]),
        ("graph_edges", [("review_status", "TEXT DEFAULT 'legacy'")]),
    ]:
        for col, col_type in cols:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass

    # Migrate graph_nodes: add updated_at if missing
    try:
        conn.execute("ALTER TABLE graph_nodes ADD COLUMN updated_at TIMESTAMP")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()
