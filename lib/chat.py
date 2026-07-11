"""Chat backend: search + LLM synthesis with citations."""
import json
import os
import re
from typing import Optional

import anthropic

from . import db


CHAT_MODEL = "claude-sonnet-4-6"

SYSTEM = """You are the user's personal librarian. They've saved hundreds of bookmarks over the years and you're helping them rediscover and synthesize what's in there.

Given a question and a list of candidate bookmarks (each with title, summary, why_saved, tags), do two things:

1. Write a synthesized answer to the question using the bookmarks as your evidence base. Be concrete. Reference what the bookmarks actually say. If the candidates don't really answer the question, say so plainly — don't pad. If there's a recurring theme worth pointing out, point it out.

2. Pick the bookmarks that genuinely support your answer (not all of them — only the ones that earn a citation). Cite by their numeric id.

Respond as JSON ONLY:
{"answer": "...prose...", "cited_ids": [12, 47, 89]}

Keep the answer to 1-2 short paragraphs unless the question genuinely needs more.
"""


def _build_client() -> anthropic.Anthropic:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set.")
    return anthropic.Anthropic(api_key=key)


def _format_candidates(candidates: list[dict]) -> str:
    lines = []
    for c in candidates:
        tags = ""
        if c.get("tags"):
            try:
                tags = ", ".join(json.loads(c["tags"]))
            except (json.JSONDecodeError, TypeError):
                tags = c["tags"]
        lines.append(
            f"[{c['id']}] {c.get('title') or '(untitled)'}\n"
            f"    URL: {c['url']}\n"
            f"    Folder: {c.get('folder') or ''}\n"
            f"    Summary: {c.get('summary') or '(none)'}\n"
            f"    Why saved: {c.get('why_saved') or '(none)'}\n"
            f"    Tags: {tags}\n"
        )
    return "\n".join(lines)


def answer(conn, question: str, *, max_candidates: int = 30, include_archived: bool = False) -> dict:
    """Returns {answer, citations: [bookmark...]}."""
    candidates = db.search(conn, question, limit=max_candidates, include_archived=include_archived)

    if not candidates:
        return {
            "answer": "I couldn't find any matching bookmarks for that. Try different keywords, or ask in a more general way — I'm searching across titles, summaries, and tags.",
            "citations": [],
            "candidates_considered": 0,
        }

    client = _build_client()
    prompt = f"Question: {question}\n\nCandidate bookmarks:\n\n{_format_candidates(candidates)}"

    try:
        resp = client.messages.create(
            model=CHAT_MODEL,
            max_tokens=1500,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        parsed = json.loads(text)
        answer_text = parsed.get("answer", "").strip()
        cited_ids = parsed.get("cited_ids", []) or []
    except (json.JSONDecodeError, anthropic.APIStatusError) as e:
        return {
            "answer": f"Error from chat model: {e}. Showing top search results without synthesis.",
            "citations": candidates[:10],
            "candidates_considered": len(candidates),
        }

    by_id = {c["id"]: c for c in candidates}
    citations = [by_id[cid] for cid in cited_ids if cid in by_id]

    # Fallback: if model cited nothing but found candidates, surface top 5
    if not citations:
        citations = candidates[:5]

    return {
        "answer": answer_text,
        "citations": citations,
        "candidates_considered": len(candidates),
    }
