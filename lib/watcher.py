"""Background watcher: monitors Chrome Bookmarks file and auto-enriches new entries."""
import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import Optional

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from lib import config, cull, db, enrich, parse

logger = logging.getLogger(__name__)


def _ingest_and_enrich(db_path: Path, bookmarks_path: Path) -> None:
    """Parse Chrome JSON, upsert new bookmarks, run enrichment pass if anything new."""
    try:
        raw = parse.parse_chrome_json(bookmarks_path)
    except Exception as exc:
        # Chrome may be mid-write (non-atomic rename); next event will retry
        logger.warning("watcher: parse failed (Chrome mid-write?): %s", exc)
        return

    kept, _ = cull.conservative_cull(raw)
    inserted = 0
    with db.connect(db_path) as conn:
        for b in kept:
            _, was_inserted = db.upsert_bookmark(
                conn, url=b["url"], title=b["title"], folder=b["folder"], add_date=b["add_date"]
            )
            if was_inserted:
                inserted += 1
        conn.commit()

    if inserted == 0:
        return

    logger.info("watcher: %d new bookmark(s) inserted, enriching...", inserted)
    with db.connect(db_path) as conn:
        asyncio.run(enrich.enrich_corpus(
            conn, batch_size=20, concurrency=8, llm_concurrency=4,
        ))


class _BookmarkHandler(FileSystemEventHandler):
    def __init__(self, bookmarks_path: Path, db_path: Path, debounce_secs: float) -> None:
        super().__init__()
        self._bookmarks_path = bookmarks_path
        self._db_path = db_path
        self._debounce_secs = debounce_secs
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self._enriching = threading.Event()

    def _schedule(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._debounce_secs, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def _fire(self) -> None:
        if self._enriching.is_set():
            logger.warning("watcher: enrichment in progress, skipping cycle")
            return
        self._enriching.set()
        try:
            _ingest_and_enrich(self._db_path, self._bookmarks_path)
        except Exception as exc:
            logger.error("watcher: unexpected error: %s", exc)
        finally:
            self._enriching.clear()

    def on_modified(self, event) -> None:
        if not event.is_directory and Path(event.src_path).name == "Bookmarks":
            self._schedule()

    def on_created(self, event) -> None:
        # Chrome uses atomic rename on some OS versions → FileCreatedEvent not FileModifiedEvent
        if not event.is_directory and Path(event.src_path).name == "Bookmarks":
            self._schedule()

    def on_moved(self, event) -> None:
        # Chrome's normal save path: write to a temp file, then rename it onto
        # "Bookmarks" — watchdog reports this as a moved event, not created/modified.
        if not event.is_directory and Path(event.dest_path).name == "Bookmarks":
            self._schedule()


def start_watcher(
    db_path: Path,
    bookmarks_path: Path,
    debounce_secs: float = config.WATCHER_DEBOUNCE_SECS,
) -> Observer:
    """Start file watcher as a daemon thread. Returns Observer (caller may call stop())."""
    if not bookmarks_path.exists():
        raise FileNotFoundError(
            f"Chrome bookmarks not found: {bookmarks_path}\n"
            "Set BRAIN_CHROME_BOOKMARKS env var to override."
        )
    handler = _BookmarkHandler(bookmarks_path, db_path, debounce_secs)
    observer = Observer()
    observer.schedule(handler, str(bookmarks_path.parent), recursive=False)
    observer.start()
    logger.info("watcher: watching %s (debounce=%.1fs)", bookmarks_path.parent, debounce_secs)
    return observer


def run_decay_loop(
    db_path: Path,
    days: int = config.DECAY_DAYS,
    interval_secs: float = 86400.0,
) -> threading.Thread:
    """Archive stale bookmarks once on startup, then daily. Returns daemon Thread."""
    def _loop() -> None:
        while True:
            try:
                with db.connect(db_path) as conn:
                    n = db.archive_stale(conn, days=days)
                if n:
                    logger.info("decay: archived %d stale bookmark(s)", n)
            except Exception as exc:
                logger.error("decay: error: %s", exc)
            time.sleep(interval_secs)

    t = threading.Thread(target=_loop, name="decay-loop", daemon=True)
    t.start()
    return t
