# Bookmark Brain

A personal librarian for your Chrome bookmarks. Parses your export, fetches each page, summarizes with
Claude, and gives you a chat interface to query the whole corpus — plus a background watcher that keeps
it in sync as you keep bookmarking.

Built around two ideas:

1. **Chat, don't browse.** Folder hierarchies rot. Replace them with natural-language search over enriched content.
2. **Decay, don't hoard.** A bookmark you haven't touched in 6 months gets archived (still searchable, but
   out of the way). Touching it via chat resets the clock.

## What's in the box

- `brain.py ingest` — parses a Chrome bookmarks export, conservatively de-junks, loads into SQLite
- `brain.py enrich` — fetches each URL, extracts main content, summarizes + tags via Claude Haiku
- `brain.py serve` — local web app with chat, plus the watcher and decay loop running alongside it
- `brain.py watch` — the watcher and decay loop only, no web UI (for headless/background use)
- `brain.py stats` — corpus health check

The **watcher** monitors your live Chrome bookmarks file and automatically ingests + enriches new
bookmarks shortly after you save them (ingestion is near-instant; enrichment adds a per-bookmark call
to Claude, so a burst of new bookmarks can take longer to fully enrich) — no manual `ingest`/`enrich`
needed once it's running.

The **decay loop** runs once at startup and then daily, archiving anything that hasn't been touched in
`BRAIN_DECAY_DAYS` (default 180). Archived bookmarks stay searchable behind an "include archived" toggle.

## Setup (one-time)

Requires Python 3.11+.

```bash
git clone https://github.com/<you>/bookmark-brain.git
cd bookmark-brain
./setup.sh
```

The setup script creates a venv, installs dependencies, and prompts for your Anthropic API key (saved to
`.env`, mode 600). If you already have an `.env` with `ANTHROPIC_API_KEY=...`, the script leaves it alone.

## Workflow

```bash
source .venv/bin/activate

# 1. Load your bookmarks — either a browser export or a live Chrome profile's Bookmarks file
python brain.py ingest ~/Downloads/bookmarks.html
# or:
python brain.py ingest "$HOME/Library/Application Support/Google/Chrome/Default/Bookmarks"

# 2. Enrich them — fetches every URL, summarizes content
#    Try a small sample first to verify everything works:
python brain.py enrich --limit 50

#    Then run the full enrichment when you're ready:
python brain.py enrich

# 3. Open the chat (also starts the watcher + decay loop)
python brain.py serve
# → http://127.0.0.1:8765
```

From here, new bookmarks you save in Chrome show up in the chat automatically — no need to re-run
`ingest`/`enrich` by hand.

## Configuration

All config is environment variables (set in `.env` or your shell), with sane defaults. Current default
values live in `lib/config.py` — that's the source of truth; `.env.example` lists the same variables
without repeating the numbers so the two can't drift out of sync.

| Variable | What it does |
|---|---|
| `ANTHROPIC_API_KEY` | *(required)* Used for enrichment and chat synthesis |
| `BRAIN_DB` | Path to the SQLite database |
| `BRAIN_CHROME_BOOKMARKS` | Which Chrome profile's `Bookmarks` file to watch |
| `BRAIN_DEBOUNCE` | Seconds to wait after a bookmarks-file change before ingesting |
| `BRAIN_DECAY_DAYS` | Days of no activity before a bookmark is archived |
| `BRAIN_USER_PERSONA` | Freeform description used to guess *why* you saved something — customize this to your own interests for sharper `why_saved` guesses |

**Finding your Chrome profile path:** open `chrome://version` in Chrome and look at "Profile Path" — that
directory contains the `Bookmarks` file. On Linux it's typically under
`~/.config/google-chrome/<Profile>/Bookmarks`; on Windows,
`%LOCALAPPDATA%\Google\Chrome\User Data\<Profile>\Bookmarks`.

## Running it in the background

`brain.py serve` (or `watch`) needs to keep running for the watcher and decay loop to work. To run it
persistently:

- **macOS:** a `launchd` user agent pointed at `.venv/bin/python3 brain.py watch` (or `serve`), with
  `RunAtLoad` and `KeepAlive` set, works well. Point `StandardOutPath`/`StandardErrorPath` at log files —
  the app logs via Python's `logging` module.
- **Linux:** a `systemd --user` service unit works the same way.

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

Clicking a citation in the UI opens the URL **and** records a "touch" — that bookmark's decay clock resets.

## Database

Single SQLite file at `bookmarks.db` in the project root. All your data, fully local. To reset: delete the
file and re-ingest.

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
├── requirements-dev.txt  ← adds pytest, for running the test suite
├── .env.example
├── lib/
│   ├── parse.py          ← Bookmarks HTML export / Chrome JSON parser
│   ├── cull.py           ← Conservative junk cull
│   ├── fetch.py          ← Async URL fetcher + content extraction
│   ├── enrich.py         ← Fetch + summarize pipeline
│   ├── llm.py            ← Shared Anthropic client + JSON response parsing
│   ├── chat.py           ← Search + LLM synthesis
│   ├── watcher.py        ← Chrome bookmarks file watcher + decay loop
│   ├── server.py         ← FastAPI app
│   ├── db.py             ← SQLite schema + helpers
│   └── config.py
├── tests/                ← pytest suite for the pure-logic modules (parse, cull, llm)
└── static/
    └── index.html        ← Chat UI
```

## Running tests

```bash
pip install -r requirements-dev.txt
pytest tests/
```

## Troubleshooting

**"ANTHROPIC_API_KEY not set"** — `cat .env` to check it's there, then `export $(cat .env | xargs)` in your shell.

**Lots of `blocked` or `dead` statuses** — expected for old bookmarks. Some sites (Cloudflare-protected, geo-blocked, deleted) just won't fetch. They'll still be searchable by title and folder.

**Enrichment feels slow** — the bottleneck is HTTP fetches, not LLM calls. Bump `--concurrency` higher if you have good bandwidth (`--concurrency 24`).

**New bookmarks aren't showing up automatically** — confirm `BRAIN_CHROME_BOOKMARKS` points at the profile
you actually bookmark in (Chrome supports multiple profiles, each with its own `Bookmarks` file), and that
`serve`/`watch` is actually running.

**Want to start over** — delete `bookmarks.db` and re-ingest.

## License

MIT — see [LICENSE](LICENSE).
