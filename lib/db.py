"""SQLite schema and helpers for the bookmark corpus."""
import sqlite3
import json
import time
from pathlib import Path
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS bookmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    title TEXT,
    folder TEXT,
    add_date INTEGER,             -- unix ts from chrome
    fetched_at INTEGER,           -- unix ts when we last fetched
    fetch_status TEXT,            -- ok | dead | timeout | blocked | error | skipped
    fetch_http_code INTEGER,
    content_text TEXT,            -- extracted main content (truncated)
    summary TEXT,                 -- LLM 2-3 sentence summary
    why_saved TEXT,               -- LLM guess at intent
    tags TEXT,                    -- JSON array of strings
    last_touched INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    archived INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
);

CREATE INDEX IF NOT EXISTS idx_archived     ON bookmarks(archived);
CREATE INDEX IF NOT EXISTS idx_last_touched ON bookmarks(last_touched);
CREATE INDEX IF NOT EXISTS idx_fetch_status ON bookmarks(fetch_status);

CREATE VIRTUAL TABLE IF NOT EXISTS bookmarks_fts USING fts5(
    title, summary, why_saved, tags, content_text,
    content='bookmarks',
    content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS bookmarks_ai AFTER INSERT ON bookmarks BEGIN
    INSERT INTO bookmarks_fts(rowid, title, summary, why_saved, tags, content_text)
    VALUES (new.id, new.title, new.summary, new.why_saved, new.tags, new.content_text);
END;

CREATE TRIGGER IF NOT EXISTS bookmarks_ad AFTER DELETE ON bookmarks BEGIN
    INSERT INTO bookmarks_fts(bookmarks_fts, rowid, title, summary, why_saved, tags, content_text)
    VALUES('delete', old.id, old.title, old.summary, old.why_saved, old.tags, old.content_text);
END;

CREATE TRIGGER IF NOT EXISTS bookmarks_au AFTER UPDATE ON bookmarks BEGIN
    INSERT INTO bookmarks_fts(bookmarks_fts, rowid, title, summary, why_saved, tags, content_text)
    VALUES('delete', old.id, old.title, old.summary, old.why_saved, old.tags, old.content_text);
    INSERT INTO bookmarks_fts(rowid, title, summary, why_saved, tags, content_text)
    VALUES (new.id, new.title, new.summary, new.why_saved, new.tags, new.content_text);
END;
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn


def upsert_bookmark(conn: sqlite3.Connection, url: str, title: str, folder: str, add_date: Optional[int]) -> int:
    """Insert or update by URL. Returns row id. Does not touch enrichment fields."""
    cur = conn.execute("SELECT id FROM bookmarks WHERE url = ?", (url,))
    row = cur.fetchone()
    if row:
        conn.execute(
            "UPDATE bookmarks SET title=?, folder=?, add_date=COALESCE(?, add_date) WHERE id=?",
            (title, folder, add_date, row["id"]),
        )
        return row["id"]
    cur = conn.execute(
        "INSERT INTO bookmarks (url, title, folder, add_date) VALUES (?, ?, ?, ?)",
        (url, title, folder, add_date),
    )
    return cur.lastrowid


def needs_enrichment(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Bookmarks that haven't been fetched yet."""
    return conn.execute(
        "SELECT id, url, title, folder FROM bookmarks WHERE fetched_at IS NULL ORDER BY id"
    ).fetchall()


def save_enrichment(
    conn: sqlite3.Connection,
    bookmark_id: int,
    fetch_status: str,
    fetch_http_code: Optional[int],
    content_text: Optional[str],
    summary: Optional[str],
    why_saved: Optional[str],
    tags: Optional[list[str]],
) -> None:
    conn.execute(
        """UPDATE bookmarks
           SET fetched_at=?, fetch_status=?, fetch_http_code=?,
               content_text=?, summary=?, why_saved=?, tags=?
           WHERE id=?""",
        (
            int(time.time()),
            fetch_status,
            fetch_http_code,
            content_text,
            summary,
            why_saved,
            json.dumps(tags) if tags else None,
            bookmark_id,
        ),
    )
    conn.commit()


_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "in", "on", "at", "to", "of", "for",
    "with", "by", "is", "are", "was", "were", "be", "been", "being", "have", "has",
    "had", "do", "does", "did", "i", "me", "my", "we", "our", "you", "your", "what",
    "which", "who", "when", "where", "why", "how", "this", "that", "these", "those",
    "show", "find", "tell", "give", "about", "any", "some", "all",
}

def search(conn: sqlite3.Connection, query: str, limit: int = 30, include_archived: bool = False) -> list[dict]:
    """FTS5 search over enriched bookmarks. Returns list of dicts."""
    import re
    # Strip FTS5-significant punctuation; keep word chars and hyphens
    tokens = re.findall(r"[A-Za-z0-9_\-]+", query.lower())
    # Drop stopwords; keep content words
    content_words = [t for t in tokens if t not in _STOPWORDS and len(t) > 1]
    if not content_words:
        # Fall back to all tokens if everything was a stopword
        content_words = [t for t in tokens if len(t) > 1]
    if not content_words:
        return []
    fts_query = " OR ".join(f'"{w}"' for w in content_words)
    archived_clause = "" if include_archived else "AND b.archived = 0"
    rows = conn.execute(
        f"""SELECT b.id, b.url, b.title, b.folder, b.summary, b.why_saved, b.tags,
                   b.fetch_status, b.add_date, b.last_touched, b.archived,
                   bm25(bookmarks_fts) AS score
            FROM bookmarks_fts
            JOIN bookmarks b ON b.id = bookmarks_fts.rowid
            WHERE bookmarks_fts MATCH ?
              AND b.fetch_status = 'ok'
              {archived_clause}
            ORDER BY score
            LIMIT ?""",
        (fts_query, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_bookmark(conn: sqlite3.Connection, bookmark_id: int) -> Optional[dict]:
    row = conn.execute("SELECT * FROM bookmarks WHERE id=?", (bookmark_id,)).fetchone()
    return dict(row) if row else None


def touch(conn: sqlite3.Connection, bookmark_id: int) -> None:
    conn.execute(
        "UPDATE bookmarks SET last_touched=?, archived=0 WHERE id=?",
        (int(time.time()), bookmark_id),
    )
    conn.commit()


def stats(conn: sqlite3.Connection) -> dict:
    total = conn.execute("SELECT COUNT(*) FROM bookmarks").fetchone()[0]
    enriched = conn.execute("SELECT COUNT(*) FROM bookmarks WHERE fetched_at IS NOT NULL").fetchone()[0]
    ok = conn.execute("SELECT COUNT(*) FROM bookmarks WHERE fetch_status='ok'").fetchone()[0]
    archived = conn.execute("SELECT COUNT(*) FROM bookmarks WHERE archived=1").fetchone()[0]
    by_status = dict(conn.execute(
        "SELECT fetch_status, COUNT(*) FROM bookmarks WHERE fetch_status IS NOT NULL GROUP BY fetch_status"
    ).fetchall())
    return {
        "total": total,
        "enriched": enriched,
        "ok": ok,
        "archived": archived,
        "by_status": by_status,
    }


def archive_stale(conn: sqlite3.Connection, days: int = 180) -> int:
    """Set archived=1 on ok bookmarks not touched in `days` days. Returns count archived."""
    cutoff = int(time.time()) - days * 86400
    cur = conn.execute(
        """UPDATE bookmarks SET archived = 1
           WHERE archived = 0
             AND fetch_status = 'ok'
             AND last_touched < ?""",
        (cutoff,),
    )
    conn.commit()
    return cur.rowcount
