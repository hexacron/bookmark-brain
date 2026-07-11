"""Enrichment pipeline: fetch URL → extract content → LLM summary + tags."""
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Optional

import anthropic

from . import db, fetch


SUMMARY_MODEL = "claude-haiku-4-5-20251001"

PROMPT = """You're cataloguing a user's saved bookmarks for retrieval. Given the page content below, return a JSON object with three fields:

- "summary": 2-3 sentences. What is this page actually about? Concrete and specific. No marketing fluff.
- "why_saved": one sentence guess at why someone professionally interested in OSINT, cybersecurity, and dev tooling would have saved this.
- "tags": 3-5 short lowercase tags (kebab-case). Include topical tags (e.g. "osint", "rust", "data-leak") and content-type tags where relevant (e.g. "github-repo", "tool", "tutorial", "academic-paper", "news-article").

Title: {title}
URL: {url}
Folder it was saved in: {folder}

Page content:
---
{content}
---

Respond with ONLY the JSON object, no preamble."""


def _build_client() -> anthropic.Anthropic:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set. Did you run setup.sh?")
    return anthropic.Anthropic(api_key=key)


def _summarize_one(client: anthropic.Anthropic, *, title: str, url: str, folder: str, content: str) -> Optional[dict]:
    """Single LLM call with retries. Returns parsed dict or None on failure."""
    prompt = PROMPT.format(title=title or "(untitled)", url=url, folder=folder or "(root)", content=content[:6000])
    for attempt in range(3):
        try:
            resp = client.messages.create(
                model=SUMMARY_MODEL,
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text.strip()
            # Strip code fences if present
            if text.startswith("```"):
                text = text.split("```", 2)[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            return json.loads(text)
        except json.JSONDecodeError:
            if attempt == 2:
                return None
        except anthropic.RateLimitError:
            time.sleep(2 ** attempt)
        except anthropic.APIStatusError:
            if attempt == 2:
                return None
            time.sleep(1)
    return None


async def enrich_corpus(conn, *, batch_size: int = 50, concurrency: int = 12, llm_concurrency: int = 6, max_items: Optional[int] = None):
    """Run enrichment over all unfetched bookmarks. Streams progress to stdout."""
    pending = db.needs_enrichment(conn)
    if max_items:
        pending = pending[:max_items]
    total = len(pending)
    if total == 0:
        print("Nothing to enrich. All bookmarks already have fetched_at set.")
        return

    print(f"Enriching {total} bookmarks (batch={batch_size}, http={concurrency}, llm={llm_concurrency})")
    client = _build_client()
    llm_sem = asyncio.Semaphore(llm_concurrency)
    processed = 0
    started = time.time()

    counters = {"ok": 0, "dead": 0, "timeout": 0, "blocked": 0, "non_html": 0, "error": 0, "no_summary": 0}

    for batch_start in range(0, total, batch_size):
        batch = pending[batch_start:batch_start + batch_size]
        urls = [b["url"] for b in batch]
        results = await fetch.fetch_many(urls, concurrency=concurrency)

        async def summarize_with_sem(b, fr):
            async with llm_sem:
                # Run blocking SDK call in a thread
                return await asyncio.to_thread(_summarize_one, client,
                    title=b["title"], url=b["url"], folder=b["folder"],
                    content=fr["content_text"] or "")

        # Kick off LLM calls only for fetches that returned usable content
        summary_tasks = []
        summary_indices = []
        for i, (b, fr) in enumerate(zip(batch, results)):
            if fr["status"] == "ok" and fr.get("content_text"):
                summary_tasks.append(summarize_with_sem(b, fr))
                summary_indices.append(i)

        summaries = await asyncio.gather(*summary_tasks) if summary_tasks else []
        sum_by_idx = dict(zip(summary_indices, summaries))

        for i, (b, fr) in enumerate(zip(batch, results)):
            status = fr["status"]
            counters[status] = counters.get(status, 0) + 1

            summary = None
            why = None
            tags = None
            content_text = fr.get("content_text")

            if status == "ok":
                s = sum_by_idx.get(i)
                if s:
                    summary = s.get("summary")
                    why = s.get("why_saved")
                    tags = s.get("tags") or []
                    if not isinstance(tags, list):
                        tags = []
                else:
                    counters["no_summary"] += 1

            db.save_enrichment(
                conn,
                bookmark_id=b["id"],
                fetch_status=status,
                fetch_http_code=fr.get("http_code"),
                content_text=content_text,
                summary=summary,
                why_saved=why,
                tags=tags,
            )
            processed += 1

        elapsed = time.time() - started
        rate = processed / elapsed if elapsed > 0 else 0
        eta = (total - processed) / rate if rate > 0 else 0
        print(f"  [{processed}/{total}] {elapsed:.0f}s elapsed, {rate:.1f}/s, ETA {eta:.0f}s "
              f"| ok={counters['ok']} dead={counters['dead']} timeout={counters['timeout']} "
              f"blocked={counters['blocked']} non_html={counters['non_html']} error={counters['error']}")

    print()
    print("Enrichment complete.")
    print(f"  ok:       {counters['ok']}")
    print(f"  dead:     {counters['dead']}")
    print(f"  timeout:  {counters['timeout']}")
    print(f"  blocked:  {counters['blocked']}")
    print(f"  non-html: {counters['non_html']}")
    print(f"  error:    {counters['error']}")
    print(f"  ok-but-no-summary: {counters['no_summary']}")
