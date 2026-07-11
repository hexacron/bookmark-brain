# Bookmark Brain

A personal librarian for your Chrome bookmarks. Parses your export, fetches each page, summarizes with Claude, and gives you a chat interface to query the whole corpus.

Built around two ideas:

1. **Chat, don't browse.** Folder hierarchies rot. Replace them with natural-language search over enriched content.
2. **Decay, don't hoard.** A bookmark you haven't touched in 6 months gets archived (still searchable, but out of the way). Touching it via chat resets the clock. *(Decay loop is phase 2 — not in this build.)*

## What's in the box

- `brain.py ingest` — parses Chrome bookmarks export, conservatively de-junks, loads into SQLite
- `brain.py enrich` — fetches each URL, extracts main content, summarizes + tags via Claude Haiku
- `brain.py serve` — local web app with chat. Synthesized answers + bookmark cards as citations.
- `brain.py stats` — corpus health check

## Setup (one-time)

Requires Python 3.11+ on macOS.

```bash
cd bookmark-brain
./setup.sh
```

The setup script creates a venv, installs dependencies, and prompts for your Anthropic API key (saved to `.env`, mode 600).

If you already have an `.env` file with `ANTHROPIC_API_KEY=...`, the script will leave it alone.

## Workflow

```bash
source .venv/bin/activate

# 1. Load your bookmarks (use HTML export OR live Chrome JSON path)
python brain.py ingest ~/Downloads/bookmarks.html
# or:
python brain.py ingest "$HOME/Library/Application Support/Google/Chrome/Default/Bookmarks"

# 2. Enrich them — fetches every URL, summarizes content
#    Try a small sample first to verify everything works:
python brain.py enrich --limit 50

#    Then run the full enrichment when you're ready:
python brain.py enrich

# 3. Open the chat
python brain.py serve
# → http://127.0.0.1:8765
```

## What enrichment costs

For ~2,000 bookmarks:

- **Time:** roughly 15–30 minutes wall-clock with default concurrency (HTTP fetches dominate; many will time out or 404).
- **Money:** roughly **$1–4** total at Haiku rates. Cheap.
- **Recoverable failures:** dead links, timeouts, and auth-walled pages get marked accordingly. You can re-run `enrich` anytime — it skips bookmarks already attempted.

## How the chat works

You type a natural-language question. The backend:

1. Runs an FTS5 search over titles, summaries, why-saved, and tags. Pulls the top 30 candidates.
2. Hands those candidates to Claude Sonnet with the question.
3. Claude writes a synthesized answer and picks which candidates earn a citation.

Clicking a citation in the UI opens the URL **and** records a "touch" — that bookmark's decay clock resets. Anything that drifts six months without a touch is on the path to archive.

## Database

Single SQLite file at `bookmarks.db` in the project root. All your data, fully local. To reset: delete the file and re-ingest.

```bash
sqlite3 bookmarks.db   # if you want to poke around
```

Schema lives in `lib/db.py`.

## File layout

```
bookmark-brain/
├── brain.py              ← CLI entry point
├── setup.sh              ← venv + deps + key prompt
├── requirements.txt
├── .env.example
├── lib/
│   ├── parse.py          ← Chrome HTML / JSON parser
│   ├── cull.py           ← Conservative junk cull
│   ├── fetch.py          ← Async URL fetcher + content extraction
│   ├── enrich.py         ← Fetch + summarize pipeline
│   ├── chat.py           ← Search + LLM synthesis
│   ├── server.py         ← FastAPI app
│   ├── db.py             ← SQLite schema + helpers
│   └── config.py
└── static/
    └── index.html        ← Chat UI
```

## Phase 2 (not in this build)

- **Decay loop**: a daily cron that archives anything `last_touched > 6 months ago`. Archive is hidden from default search but still queryable with the toggle.
- **Chrome file watcher**: watches `~/Library/Application Support/Google/Chrome/Default/Bookmarks` for new entries and auto-enriches them. New bookmarks appear in the brain within a minute of saving in Chrome.

Both are easy adds once you've used the chat for a week and confirmed the corpus is doing what you want.

## Troubleshooting

**"ANTHROPIC_API_KEY not set"** — `cat .env` to check it's there, then `export $(cat .env | xargs)` in your shell.

**Lots of `blocked` or `dead` statuses** — expected for old bookmarks. Some sites (Cloudflare-protected, geo-blocked, deleted) just won't fetch. They'll still be searchable by title and folder.

**Enrichment feels slow** — the bottleneck is HTTP fetches, not LLM calls. Bump `--concurrency` higher if you have good bandwidth (`--concurrency 24`).

**Want to start over** — delete `bookmarks.db` and re-ingest.
