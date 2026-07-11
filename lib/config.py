"""Paths and small config helpers."""
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("BRAIN_DB", str(ROOT / "bookmarks.db")))

CHROME_BOOKMARKS = Path(os.environ.get(
    "BRAIN_CHROME_BOOKMARKS",
    str(Path.home() / "Library/Application Support/Google/Chrome/Default/Bookmarks"),
))
WATCHER_DEBOUNCE_SECS = float(os.environ.get("BRAIN_DEBOUNCE", "4"))
DECAY_DAYS = int(os.environ.get("BRAIN_DECAY_DAYS", "180"))
