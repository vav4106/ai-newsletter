#!/usr/bin/env python3
"""
Anthropic News Scraper
----------------------
Anthropic does not publish an official RSS feed. This scraper
fetches https://www.anthropic.com/news, extracts the list of
news items, normalizes them to the same schema used by ingest_rss.py,
and stores them in the shared SQLite database (with deduplication).

Usage:
    python scrape_anthropic.py
    python scrape_anthropic.py --dry-run
    python scrape_anthropic.py --days 60
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

# Re-use helpers from the main ingest script where possible
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingest_rss import (  # noqa: E402
    SCHEMA,
    clean_text,
    existing_ids,
    init_db,
    insert_article,
    make_hash,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("anthropic")

NEWS_URL = "https://www.anthropic.com/news"
BASE_URL = "https://www.anthropic.com"
USER_AGENT = (
    "Mozilla/5.0 (compatible; AI-Newsletter-Bot/1.0; "
    "+https://your-newsletter-site.example)"
)
SOURCE_NAME = "Anthropic News"
CATEGORY = "company"
IMPORTANCE = "high"


def fetch_page(url: str = NEWS_URL) -> Optional[str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=25)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        log.error("Failed to fetch %s: %s", url, e)
        return None


def parse_date_loose(text: str) -> Optional[datetime]:
    """Try to extract a date from mixed text like 'Aug 7, 2026 Product'."""
    # Common patterns: "Aug 7, 2026", "July 24, 2026", "Jul 30, 2026"
    patterns = [
        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})",
        r"(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4})",
        r"(\d{4}-\d{2}-\d{2})",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                dt = date_parser.parse(m.group(1), fuzzy=True)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except (ValueError, OverflowError):
                continue
    return None


def extract_title(text: str) -> str:
    """
    Strip leading date + optional category from Anthropic list/card text.

    Examples:
      "Aug 7, 2026 Product Improving Fable 5's biology safeguards"
      → "Improving Fable 5's biology safeguards"
      "Announcements Jul 9, 2026 Inviting hard questions We’re asking…"
      → "Inviting hard questions"
    """
    text = clean_text(text)
    if not text:
        return ""

    # Remove leading date
    text = re.sub(
        r"^(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # Remove leading category (single or multi-word)
    text = re.sub(
        r"^(?:Product|Announcements?|Features?|Company|Research|"
        r"Economic Research|Safety|Policy|Engineering)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # Sometimes date appears after category
    text = re.sub(
        r"^(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Remove residual date fragments that sometimes remain on featured cards
    text = re.sub(
        r"\s+(?:Product|Announcements?|Features?)\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}.*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}.*$",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Truncate long descriptions that cards append after the title
    if len(text) > 110:
        # Cut at a natural break (capital letter starting a new sentence)
        m = re.match(r"^(.{25,110}?)(?:\s+[A-Z]|\s*$)", text)
        if m:
            text = m.group(1).rstrip(" .")
        else:
            text = text[:100].rsplit(" ", 1)[0]

    return text.strip(" .") or text[:80]


def extract_items(html: str) -> List[Dict]:
    """
    Parse the Anthropic news page.

    Prefer the clean <li> list items; also capture featured cards.
    """
    soup = BeautifulSoup(html, "lxml")
    items: List[Dict] = []
    seen_slugs: Set[str] = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        # Accept both relative and absolute news links
        if "/news/" not in href:
            continue
        # Normalize to path
        if href.startswith("http"):
            path = href.replace(BASE_URL, "")
        else:
            path = href
        parts = path.rstrip("/").split("/")
        if len(parts) < 3 or parts[-1] in ("", "news"):
            continue
        slug = parts[-1]
        if slug in seen_slugs:
            continue
        # Skip known non-article pages
        if slug in ("responsible-scaling-policy", "press-kit"):
            continue
        seen_slugs.add(slug)

        full_url = urljoin(BASE_URL, path.split("?")[0].split("#")[0])
        link_text = a.get_text(" ", strip=True)

        # Prefer the tightest parent that still contains useful text
        # (list items are ideal; featured cards are larger)
        block_text = link_text
        parent = a.parent
        if parent and parent.name in ("li", "h2", "h3", "h4"):
            block_text = parent.get_text(" ", strip=True)
        elif parent:
            # one level up is often enough for cards
            block_text = parent.get_text(" ", strip=True)

        title = extract_title(link_text) or extract_title(block_text)
        if not title or len(title) < 8:
            title = slug.replace("-", " ").title()

        published = parse_date_loose(link_text) or parse_date_loose(block_text)

        # Short summary from remainder of the block (if any)
        summary = ""
        if block_text and title and title in block_text:
            after = block_text.split(title, 1)[-1]
            summary = clean_text(after)[:400]

        items.append(
            {
                "title": title,
                "link": full_url,
                "summary": summary,
                "published_at": published,
                "slug": slug,
            }
        )

    items.sort(
        key=lambda x: x["published_at"] or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return items


def normalize_item(raw: Dict) -> Dict:
    title = raw["title"]
    link = raw["link"]
    item_id = make_hash(title, link)
    published = raw.get("published_at")
    return {
        "id": item_id,
        "title": title,
        "link": link,
        "summary": raw.get("summary") or "",
        "published_at": published.isoformat() if published else None,
        "source_name": SOURCE_NAME,
        "source_url": NEWS_URL,
        "category": CATEGORY,
        "importance": IMPORTANCE,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "raw": {"slug": raw.get("slug")},
    }


def run_scraper(
    dry_run: bool = False,
    days: Optional[int] = None,
    db_path: Path = Path("data/ai_news.db"),
) -> dict:
    log.info("Fetching Anthropic news page…")
    html = fetch_page()
    if not html:
        return {"new": 0, "total": 0}

    raw_items = extract_items(html)
    log.info("Parsed %d candidate items from page", len(raw_items))

    min_date = None
    if days is not None:
        min_date = datetime.now(timezone.utc) - timedelta(days=days)

    known_ids: Set[str] = set()
    conn = None
    if not dry_run:
        conn = init_db(db_path)
        known_ids = existing_ids(conn)

    new_items = []
    for raw in raw_items:
        if min_date and raw.get("published_at") and raw["published_at"] < min_date:
            continue
        item = normalize_item(raw)
        if item["id"] in known_ids:
            continue
        new_items.append(item)
        known_ids.add(item["id"])

    if not dry_run and conn and new_items:
        for item in new_items:
            insert_article(conn, item)
        conn.commit()
        conn.close()
        log.info("Wrote %d new Anthropic articles to %s", len(new_items), db_path)

        # Also write a small JSON snapshot
        archive = Path("data") / f"anthropic_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
        archive.parent.mkdir(parents=True, exist_ok=True)
        with open(archive, "w", encoding="utf-8") as f:
            json.dump(new_items, f, ensure_ascii=False, indent=2)
        log.info("JSON archive: %s", archive)
    elif dry_run:
        for item in new_items[:12]:
            log.info(
                "  [DRY] %s | %s | %s",
                item["published_at"] or "no-date",
                item["title"][:70],
                item["link"],
            )

    return {"new": len(new_items), "total": len(raw_items)}


def main():
    parser = argparse.ArgumentParser(description="Scrape Anthropic News")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--days", type=int, help="Only keep items newer than N days")
    parser.add_argument(
        "--db",
        default="data/ai_news.db",
        help="Path to SQLite database",
    )
    args = parser.parse_args()

    result = run_scraper(
        dry_run=args.dry_run,
        days=args.days,
        db_path=Path(args.db),
    )
    log.info("Done. New articles: %d (parsed %d total)", result["new"], result["total"])


if __name__ == "__main__":
    main()