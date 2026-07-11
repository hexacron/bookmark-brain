"""Conservative cull pass: drops obvious junk before enrichment."""
from urllib.parse import urlparse
from collections import defaultdict


JUNK_SCHEMES = {
    "chrome", "chrome-extension", "about", "edge", "brave", "opera",
    "vivaldi", "file", "data", "javascript", "view-source",
}
JUNK_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0"}


def conservative_cull(bookmarks: list[dict]) -> tuple[list[dict], dict[str, list[dict]]]:
    """Returns (kept, removed_by_reason)."""
    removed: dict[str, list[dict]] = defaultdict(list)
    kept: list[dict] = []
    seen_urls: dict[str, int] = {}  # url -> kept index

    for b in bookmarks:
        url = (b.get("url") or "").strip()
        if not url:
            removed["empty_url"].append(b); continue

        parsed = urlparse(url)
        scheme = parsed.scheme.lower()

        if scheme in JUNK_SCHEMES:
            removed[f"scheme_{scheme}"].append(b); continue
        if scheme not in ("http", "https"):
            removed["no_http"].append(b); continue
        if not parsed.netloc:
            removed["no_host"].append(b); continue

        host = parsed.netloc.lower()
        if host in JUNK_HOSTS or host.startswith("localhost:") or host.startswith("127.0.0.1:"):
            removed["localhost"].append(b); continue

        # Dedupe by URL — keep the more recent entry
        if url in seen_urls:
            existing_idx = seen_urls[url]
            existing = kept[existing_idx]
            new_date = b.get("add_date") or 0
            existing_date = existing.get("add_date") or 0
            if new_date > existing_date:
                removed["duplicate"].append(existing)
                kept[existing_idx] = b
            else:
                removed["duplicate"].append(b)
            continue

        seen_urls[url] = len(kept)
        kept.append(b)

    return kept, dict(removed)
