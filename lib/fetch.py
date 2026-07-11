"""Async URL fetching with content extraction."""
import asyncio
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Limit content extraction to keep token costs sane
MAX_CONTENT_CHARS = 6000


def extract_main_text(html: str) -> str:
    """Best-effort extraction of main page content. Falls back to all text."""
    soup = BeautifulSoup(html, "html.parser")

    # Drop noise
    for tag in soup(["script", "style", "noscript", "iframe", "svg", "form",
                     "nav", "footer", "header", "aside"]):
        tag.decompose()

    # Prefer <main>, <article>, or the largest text block
    main = soup.find("main") or soup.find("article")
    if main:
        text = main.get_text(separator=" ", strip=True)
    else:
        text = soup.get_text(separator=" ", strip=True)

    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_CONTENT_CHARS]


async def fetch_one(client: httpx.AsyncClient, url: str, timeout: float = 12.0) -> dict:
    """Fetch a single URL. Returns dict with status, http_code, content_text, title_html."""
    result = {
        "status": "error",
        "http_code": None,
        "content_text": None,
        "title_html": None,
        "final_url": url,
    }
    try:
        r = await client.get(url, timeout=timeout, follow_redirects=True,
                              headers={"User-Agent": USER_AGENT,
                                       "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                                       "Accept-Language": "en-US,en;q=0.9"})
        result["http_code"] = r.status_code
        result["final_url"] = str(r.url)

        if r.status_code == 200:
            ctype = (r.headers.get("content-type") or "").lower()
            if "text/html" in ctype or "application/xhtml" in ctype or ctype == "":
                html = r.text
                result["content_text"] = extract_main_text(html)
                # Pull <title> directly for fallback
                soup = BeautifulSoup(html, "html.parser")
                if soup.title and soup.title.string:
                    result["title_html"] = soup.title.string.strip()[:200]
                result["status"] = "ok"
            else:
                # Non-HTML (PDF, video, etc.) — can't summarize easily
                result["status"] = "non_html"
        elif r.status_code in (401, 403):
            result["status"] = "blocked"
        elif r.status_code in (404, 410):
            result["status"] = "dead"
        else:
            result["status"] = "error"
    except httpx.TimeoutException:
        result["status"] = "timeout"
    except (httpx.ConnectError, httpx.ReadError, httpx.NetworkError):
        result["status"] = "dead"
    except Exception:
        result["status"] = "error"
    return result


async def fetch_many(urls: list[str], concurrency: int = 12, timeout: float = 12.0) -> list[dict]:
    """Fetch URLs in parallel, capped at `concurrency`. Returns results in input order."""
    sem = asyncio.Semaphore(concurrency)
    limits = httpx.Limits(max_connections=concurrency * 2, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(limits=limits, http2=False) as client:
        async def bounded(u: str) -> dict:
            async with sem:
                return await fetch_one(client, u, timeout=timeout)
        return await asyncio.gather(*(bounded(u) for u in urls))
