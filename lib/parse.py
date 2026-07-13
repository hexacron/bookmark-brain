"""Parse Chrome bookmarks export (Netscape HTML format) and Chrome's native JSON file."""
from html.parser import HTMLParser
from pathlib import Path
import json
from typing import Optional


class _NetscapeBookmarkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.bookmarks: list[dict] = []
        self.folder_stack: list[str] = []
        self._attrs: dict = {}
        self._capture_text = False
        self._buf = ""
        self._tag = None  # 'A' or 'H3'

    def handle_starttag(self, tag, attrs):
        t = tag.upper()
        if t == "A":
            self._attrs = dict(attrs)
            self._capture_text = True
            self._buf = ""
            self._tag = "A"
        elif t == "H3":
            self._attrs = dict(attrs)
            self._capture_text = True
            self._buf = ""
            self._tag = "H3"

    def handle_endtag(self, tag):
        t = tag.upper()
        if t == "A" and self._tag == "A":
            href = self._attrs.get("href", "")
            add_date = self._attrs.get("add_date", "")
            self.bookmarks.append({
                "title": self._buf.strip(),
                "url": href,
                "add_date": int(add_date) if add_date.isdigit() else None,
                "folder": "/".join(self.folder_stack) if self.folder_stack else "(root)",
            })
            self._capture_text = False
            self._tag = None
        elif t == "H3" and self._tag == "H3":
            self.folder_stack.append(self._buf.strip())
            self._capture_text = False
            self._tag = None
        elif t == "DL" and self.folder_stack:
            self.folder_stack.pop()

    def handle_data(self, data):
        if self._capture_text:
            self._buf += data


def parse_html_export(path: Path) -> list[dict]:
    """Parse a Netscape-format bookmarks HTML export."""
    p = _NetscapeBookmarkParser()
    p.feed(Path(path).read_text(encoding="utf-8"))
    return p.bookmarks


def parse_chrome_json(path: Path) -> list[dict]:
    """Parse Chrome's live ~/Library/Application Support/Google/Chrome/<Profile>/Bookmarks JSON file."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out: list[dict] = []

    def walk(node: dict, folder_path: list[str]):
        node_type = node.get("type")
        if node_type == "url":
            date_added = node.get("date_added", "")
            # Chrome stores microseconds-since-1601, convert to unix seconds
            ts = None
            if date_added.isdigit():
                ts = int(int(date_added) / 1_000_000 - 11_644_473_600)
            out.append({
                "title": node.get("name", ""),
                "url": node.get("url", ""),
                "add_date": ts,
                "folder": "/".join(folder_path) if folder_path else "(root)",
            })
        elif node_type == "folder":
            name = node.get("name", "")
            sub_path = folder_path + [name] if name else folder_path
            for child in node.get("children", []):
                walk(child, sub_path)

    roots = data.get("roots", {})
    for root_key in ("bookmark_bar", "other", "synced"):
        node = roots.get(root_key)
        if node:
            walk(node, [])
    return out


def parse_any(path: Path) -> list[dict]:
    """Auto-detect format by extension, or by content for extensionless files."""
    p = Path(path)
    if p.suffix.lower() in (".html", ".htm"):
        return parse_html_export(p)
    if p.suffix.lower() == ".json" or p.name == "Bookmarks":
        return parse_chrome_json(p)

    # No recognizable extension: sniff the content instead of guessing blindly.
    text = p.read_text(encoding="utf-8")
    stripped = text.lstrip()
    if stripped.startswith("{"):
        return parse_chrome_json(p)
    if stripped.startswith("<"):
        return parse_html_export(p)
    raise ValueError(
        f"Could not detect bookmarks format for {p}: expected HTML export or Chrome JSON."
    )
