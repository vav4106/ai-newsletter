#!/usr/bin/env python3
"""
Fetch full article bodies for items that only have short/empty summaries.

Works especially well for Anthropic (and other sites with clean <article> tags).
Updates the shared SQLite database in place.

Usage:
    python fetch_bodies.py                     # process items missing body
    python fetch_bodies.py --source Anthropic  # only one source
    python fetch_bodies.py --limit 20
    python fetch_bodies.py --dry-run
    python fetch_bodies.py --force             # re-fetch even if body exists
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("bodies")

USER_AGENT = (
    "Mozilla/5.0 (compatible; AI-Newsletter-Bot/1.0; "
    "+https://your-newsletter-site.example)"
)
DB_PATH = Path(__file__).resolve().parent / "data" / "ai_news.db"

# ---------------------------------------------------------------------------
# Schema extension
# ---------------------------------------------------------------------------
def ensure_schema(conn: sqlite3.Connection) -> None:
    """Add body + fetch_status columns if missing."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(articles)")}
    for col, sql in [
        ("body", "ALTER TABLE articles ADD COLUMN body TEXT"),
        ("fetch_status", "ALTER TABLE articles ADD COLUMN fetch_status TEXT"),
        # fetch_status values: ok | blocked_403 | blocked_429 | error | empty | skipped
    ]:
        if col not in cols:
            log.info("Adding '%s' column to articles table", col)
            try:
                conn.execute(sql)
                conn.commit()
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e).lower():
                    raise


# ---------------------------------------------------------------------------
# Body extraction
# ---------------------------------------------------------------------------
def clean_body(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_body_generic(soup: BeautifulSoup) -> str:
    """Best-effort extraction for unknown sites."""
    # Prefer semantic tags
    for sel in ("article", "main", "[role=main]"):
        el = soup.select_one(sel)
        if el:
            paras = el.find_all(["p", "h2", "h3", "li"])
            texts = [p.get_text(" ", strip=True) for p in paras if p.get_text(strip=True)]
            if len(" ".join(texts)) > 200:
                return clean_body("\n\n".join(texts))

    # Fallback: largest text block of paragraphs
    candidates = []
    for div in soup.find_all(["div", "section"]):
        paras = div.find_all("p", recursive=False)
        if len(paras) >= 3:
            t = "\n\n".join(p.get_text(" ", strip=True) for p in paras)
            candidates.append(t)
    if candidates:
        best = max(candidates, key=len)
        return clean_body(best)
    return ""


def extract_body_anthropic(soup: BeautifulSoup) -> str:
    article = soup.find("article")
    if not article:
        return extract_body_generic(soup)
    parts = []
    for el in article.find_all(["p", "h2", "h3", "li", "blockquote"]):
        t = el.get_text(" ", strip=True)
        if t and len(t) > 15:
            parts.append(t)
    return clean_body("\n\n".join(parts))


def extract_body_openai(soup: BeautifulSoup) -> str:
    # OpenAI news pages often use prose-like containers
    for sel in ("article", "[class*=prose]", "main"):
        el = soup.select_one(sel)
        if el:
            paras = el.find_all(["p", "h2", "h3", "li"])
            texts = [p.get_text(" ", strip=True) for p in paras if len(p.get_text(strip=True)) > 20]
            if texts:
                return clean_body("\n\n".join(texts))
    return extract_body_generic(soup)


EXTRACTORS = {
    "anthropic.com": extract_body_anthropic,
    "openai.com": extract_body_openai,
    "deepmind.google": extract_body_generic,
    "blog.google": extract_body_generic,
    "huggingface.co": extract_body_generic,
}

# Domains known to block simple bots (updated at runtime too)
KNOWN_BLOCKED_DOMAINS = {
    "openai.com",  # consistently returns 403
}

# Status codes that mean "don't retry soon"
BLOCK_STATUS_CODES = {401, 403, 451}


class FetchResult:
    """Structured result from a body fetch attempt."""

    __slots__ = ("body", "status", "http_code", "message", "domain")

    def __init__(
        self,
        body: str = "",
        status: str = "error",
        http_code: Optional[int] = None,
        message: str = "",
        domain: str = "",
    ):
        self.body = body
        self.status = status  # ok | blocked_403 | blocked_429 | error | empty
        self.http_code = http_code
        self.message = message
        self.domain = domain


def domain_from_url(url: str) -> str:
    return urlparse(url).netloc.lower().replace("www.", "")


def fetch_and_extract(url: str, timeout: int = 25) -> FetchResult:
    """
    Fetch a page and extract the main article body.
    Handles 403/401/429/5xx explicitly and returns a structured result.
    """
    domain = domain_from_url(url)

    # Fast-path: known blocked domains
    if domain in KNOWN_BLOCKED_DOMAINS:
        return FetchResult(
            status="blocked_403",
            http_code=403,
            message=f"Domain {domain} is on the known-blocked list (skipping request)",
            domain=domain,
        )

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }

    try:
        resp = requests.get(
            url,
            headers=headers,
            timeout=timeout,
            allow_redirects=True,
        )
    except requests.Timeout:
        return FetchResult(
            status="error",
            message="Request timed out",
            domain=domain,
        )
    except requests.ConnectionError as e:
        return FetchResult(
            status="error",
            message=f"Connection error: {e}",
            domain=domain,
        )
    except requests.RequestException as e:
        return FetchResult(
            status="error",
            message=f"Request failed: {e}",
            domain=domain,
        )

    code = resp.status_code

    # --- Explicit HTTP error handling ---
    if code in BLOCK_STATUS_CODES:
        # Remember this domain so later items in the same run are skipped
        KNOWN_BLOCKED_DOMAINS.add(domain)
        status = f"blocked_{code}"
        return FetchResult(
            status=status,
            http_code=code,
            message=f"HTTP {code} Forbidden/Unauthorized – site is blocking bots",
            domain=domain,
        )

    if code == 429:
        return FetchResult(
            status="blocked_429",
            http_code=429,
            message="HTTP 429 Too Many Requests – rate limited",
            domain=domain,
        )

    if code >= 500:
        return FetchResult(
            status="error",
            http_code=code,
            message=f"HTTP {code} server error",
            domain=domain,
        )

    if code >= 400:
        return FetchResult(
            status="error",
            http_code=code,
            message=f"HTTP {code} client error",
            domain=domain,
        )

    # Success path – extract body
    try:
        soup = BeautifulSoup(resp.content, "lxml")
    except Exception as e:
        return FetchResult(
            status="error",
            http_code=code,
            message=f"HTML parse error: {e}",
            domain=domain,
        )

    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
        tag.decompose()

    extractor = extract_body_generic
    for key, fn in EXTRACTORS.items():
        if key in domain:
            extractor = fn
            break

    body = extractor(soup)
    if len(body) > 25000:
        body = body[:24997] + "..."

    if not body or len(body) < 50:
        return FetchResult(
            status="empty",
            http_code=code,
            message="Page fetched but no usable article body found",
            domain=domain,
        )

    return FetchResult(
        body=body,
        status="ok",
        http_code=code,
        message="ok",
        domain=domain,
    )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def process(
    source_filter: Optional[str] = None,
    limit: int = 50,
    dry_run: bool = False,
    force: bool = False,
    delay: float = 1.2,
) -> dict:
    if not DB_PATH.exists():
        log.error("Database not found: %s", DB_PATH)
        return {"updated": 0, "failed": 0, "blocked": 0, "candidates": 0}

    conn = sqlite3.connect(str(DB_PATH))
    ensure_schema(conn)

    conditions = ["1=1"]
    params: list = []
    if source_filter:
        conditions.append("source_name LIKE ?")
        params.append(f"%{source_filter}%")
    if not force:
        # Skip items that already have a usable body
        conditions.append("(body IS NULL OR body = '' OR length(body) < 80)")
        # Skip items we already know are blocked (unless --force)
        conditions.append(
            "(fetch_status IS NULL OR fetch_status NOT IN "
            "('blocked_403', 'blocked_401', 'blocked_451'))"
        )
        # Prefer thin summaries
        conditions.append("(summary IS NULL OR length(summary) < 300)")

    where = " AND ".join(conditions)
    sql = f"""
        SELECT id, title, link, source_name, summary, fetch_status
        FROM articles
        WHERE {where}
        ORDER BY published_at DESC NULLS LAST
        LIMIT ?
    """
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    log.info("Candidates to fetch: %d", len(rows))

    stats = {"updated": 0, "failed": 0, "blocked": 0, "empty": 0, "skipped": 0}
    # Domains that returned 403 during this run – skip remaining items from them
    blocked_this_run: set[str] = set()

    for i, (item_id, title, link, source, summary, prev_status) in enumerate(rows, 1):
        domain = domain_from_url(link)

        # Skip if we already hit a hard block for this domain in the current run
        if domain in blocked_this_run or domain in KNOWN_BLOCKED_DOMAINS:
            log.info(
                "[%d/%d] %s — %s  → SKIPPED (domain blocked: %s)",
                i, len(rows), source, title[:50], domain,
            )
            if not dry_run:
                conn.execute(
                    "UPDATE articles SET fetch_status = ? WHERE id = ?",
                    ("blocked_403", item_id),
                )
                conn.commit()
            stats["skipped"] += 1
            stats["blocked"] += 1
            continue

        log.info("[%d/%d] %s — %s", i, len(rows), source, title[:60])
        result = fetch_and_extract(link)

        if result.status == "ok":
            log.info("  → %d chars (HTTP %s)", len(result.body), result.http_code)
            if not dry_run:
                new_summary = summary
                if not summary or len(summary) < 80:
                    new_summary = result.body[:400].rsplit(" ", 1)[0] + "…"
                conn.execute(
                    "UPDATE articles SET body = ?, summary = ?, fetch_status = ? WHERE id = ?",
                    (result.body, new_summary, "ok", item_id),
                )
                conn.commit()
            stats["updated"] += 1

        elif result.status.startswith("blocked_"):
            log.warning(
                "  → BLOCKED %s (HTTP %s) – %s",
                result.status,
                result.http_code,
                result.message,
            )
            blocked_this_run.add(domain)
            KNOWN_BLOCKED_DOMAINS.add(domain)
            if not dry_run:
                conn.execute(
                    "UPDATE articles SET fetch_status = ? WHERE id = ?",
                    (result.status, item_id),
                )
                conn.commit()
            stats["blocked"] += 1

            # Extra cool-down after a hard block
            if result.http_code == 429:
                log.info("  → cooling down 15s after rate-limit…")
                time.sleep(15)

        elif result.status == "empty":
            log.warning("  → empty body: %s", result.message)
            if not dry_run:
                conn.execute(
                    "UPDATE articles SET fetch_status = ? WHERE id = ?",
                    ("empty", item_id),
                )
                conn.commit()
            stats["empty"] += 1

        else:  # generic error
            log.warning("  → error: %s", result.message)
            if not dry_run:
                conn.execute(
                    "UPDATE articles SET fetch_status = ? WHERE id = ?",
                    ("error", item_id),
                )
                conn.commit()
            stats["failed"] += 1

        time.sleep(delay)

    conn.close()

    if blocked_this_run:
        log.info(
            "Domains blocked this run (will be skipped on future runs): %s",
            ", ".join(sorted(blocked_this_run)),
        )

    stats["candidates"] = len(rows)
    return stats


def main():
    parser = argparse.ArgumentParser(description="Fetch full article bodies")
    parser.add_argument("--source", type=str, help="Filter by source name substring")
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Re-fetch even if body/status exists")
    parser.add_argument("--delay", type=float, default=1.2, help="Seconds between requests")
    args = parser.parse_args()

    result = process(
        source_filter=args.source,
        limit=args.limit,
        dry_run=args.dry_run,
        force=args.force,
        delay=args.delay,
    )
    log.info(
        "Done. Updated: %d  Blocked: %d  Failed: %d  Empty: %d  Skipped: %d  Candidates: %d",
        result["updated"],
        result["blocked"],
        result["failed"],
        result.get("empty", 0),
        result.get("skipped", 0),
        result["candidates"],
    )


if __name__ == "__main__":
    main()
