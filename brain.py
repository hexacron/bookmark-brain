#!/usr/bin/env python3
"""
Bookmark Brain — main CLI.

Usage:
    python brain.py ingest <bookmarks.html|Bookmarks>     # parse + cull, load into DB
    python brain.py enrich [--limit N]                    # fetch + summarize
    python brain.py serve [--port 8765]                   # start chat web app
    python brain.py stats                                  # corpus stats
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Load .env (silent if missing)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from lib import config


def cmd_ingest(args):
    from lib import db, parse, cull
    src = Path(args.source)
    if not src.exists():
        print(f"Error: {src} not found", file=sys.stderr)
        sys.exit(1)
    print(f"Parsing {src}...")
    raw = parse.parse_any(src)
    print(f"  parsed: {len(raw):,} bookmarks")

    kept, removed = cull.conservative_cull(raw)
    print(f"  culled: -{sum(len(v) for v in removed.values())} (junk + duplicates)")
    for reason, items in sorted(removed.items(), key=lambda x: -len(x[1])):
        print(f"      {len(items):4d}  {reason}")
    print(f"  kept:   {len(kept):,}")

    print(f"\nLoading into {config.DB_PATH}...")
    inserted = 0
    updated = 0
    with db.connect(config.DB_PATH) as conn:
        for b in kept:
            _, was_inserted = db.upsert_bookmark(
                conn, url=b["url"], title=b["title"], folder=b["folder"], add_date=b["add_date"]
            )
            if was_inserted:
                inserted += 1
            else:
                updated += 1
        conn.commit()
    print(f"  inserted: {inserted}, updated: {updated}")
    print(f"\nNext: python brain.py enrich")


def cmd_enrich(args):
    from lib import db, enrich
    if not Path(config.DB_PATH).exists():
        print(f"No database at {config.DB_PATH}. Run `python brain.py ingest <bookmarks.html>` first.", file=sys.stderr)
        sys.exit(1)
    with db.connect(config.DB_PATH) as conn:
        asyncio.run(enrich.enrich_corpus(
            conn,
            batch_size=args.batch,
            concurrency=args.concurrency,
            llm_concurrency=args.llm_concurrency,
            max_items=args.limit,
        ))


def cmd_serve(args):
    if not Path(config.DB_PATH).exists():
        print(f"No database at {config.DB_PATH}. Run ingest + enrich first.", file=sys.stderr)
        sys.exit(1)
    import uvicorn
    from lib.server import create_app
    from lib import watcher as watcher_mod
    app = create_app(config.DB_PATH)
    try:
        watcher_mod.start_watcher(config.DB_PATH, config.CHROME_BOOKMARKS)
        watcher_mod.run_decay_loop(config.DB_PATH, days=config.DECAY_DAYS)
        print(f"Watching {config.CHROME_BOOKMARKS} for new bookmarks...")
    except FileNotFoundError as exc:
        print(f"Warning: watcher disabled — {exc}", file=sys.stderr)
    print(f"Bookmark Brain → http://127.0.0.1:{args.port}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


def cmd_watch(args):
    if not Path(config.DB_PATH).exists():
        print(f"No database at {config.DB_PATH}. Run ingest first.", file=sys.stderr)
        sys.exit(1)
    from lib import watcher as watcher_mod
    observer = watcher_mod.start_watcher(config.DB_PATH, config.CHROME_BOOKMARKS)
    watcher_mod.run_decay_loop(config.DB_PATH, days=config.DECAY_DAYS)
    print(f"Watching {config.CHROME_BOOKMARKS} — Ctrl-C to stop")
    try:
        while observer.is_alive():
            observer.join(timeout=1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    print("Watcher stopped.")


def cmd_stats(args):
    from lib import db
    if not Path(config.DB_PATH).exists():
        print(f"No database at {config.DB_PATH}.", file=sys.stderr)
        sys.exit(1)
    with db.connect(config.DB_PATH) as conn:
        s = db.stats(conn)
    print(f"Total:    {s['total']}")
    print(f"Enriched: {s['enriched']}")
    print(f"Active:   {s['ok']}")
    print(f"Archived: {s['archived']}")
    print()
    print("By fetch status:")
    for status, count in sorted(s["by_status"].items(), key=lambda x: -x[1]):
        print(f"  {status:12s} {count}")


def main():
    p = argparse.ArgumentParser(prog="brain", description="Bookmark Brain CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    ingest = sub.add_parser("ingest", help="Parse + cull + load bookmarks file")
    ingest.add_argument("source", help="Bookmarks HTML export or Chrome Bookmarks JSON")
    ingest.set_defaults(func=cmd_ingest)

    enrich_cmd = sub.add_parser("enrich", help="Fetch + summarize all unenriched bookmarks")
    enrich_cmd.add_argument("--limit", type=int, default=None, help="Cap items processed (for testing)")
    enrich_cmd.add_argument("--batch", type=int, default=50, help="Batch size")
    enrich_cmd.add_argument("--concurrency", type=int, default=12, help="Parallel HTTP fetches")
    enrich_cmd.add_argument("--llm-concurrency", type=int, default=6, help="Parallel LLM calls")
    enrich_cmd.set_defaults(func=cmd_enrich)

    serve = sub.add_parser("serve", help="Start the chat web app")
    serve.add_argument("--port", type=int, default=8765)
    serve.set_defaults(func=cmd_serve)

    stats = sub.add_parser("stats", help="Show corpus stats")
    stats.set_defaults(func=cmd_stats)

    watch_cmd = sub.add_parser("watch", help="Watch Chrome + auto-enrich (no web UI)")
    watch_cmd.set_defaults(func=cmd_watch)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
