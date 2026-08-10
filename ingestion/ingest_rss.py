#!/usr/bin/env python3
"""
AI Newsletter – RSS Feed Ingestion Script
-----------------------------------------
Fetches configured RSS feeds, normalizes items, deduplicates,
and stores them in SQLite + optional JSON archive.

Usage:
    python ingest_rss.py                  # normal run
    python ingest_rss.py --dry-run        # parse only, no write
    python ingest_rss.py --feed "OpenAI"  # single feed by name substring
    python ingest_rss.py --days 3         # only items newer than N days
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

import feedparser
import requests
import yaml
from dateutil import parser as date_parser

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("ingest")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def load_config(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def make_hash(title: str, link: str) -> str:
    """Stable content hash for deduplication."""
    key = f"{title.strip().lower()}|{link.strip().lower()}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def clean_text(text: Optional[str]) -> str:
    if not text:
        return ""
    # Strip HTML tags lightly
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_date(entry: dict) -> Optional[datetime]:
    """Best-effort date extraction from feedparser entry."""
    for key in ("published", "updated", "created"):
        raw = entry.get(key)
        if raw:
            try:
                dt = date_parser.parse(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except (ValueError, TypeError, OverflowError):
                continue
    # fallback to structured time
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def fetch_feed(url: str, user_agent: str, timeout: int) -> Optional[feedparser.FeedParserDict]:
    headers = {
        "User-Agent": user_agent,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
    except requests.Timeout:
        log.warning("Timeout fetching %s", url)
        return None
    except requests.RequestException as e:
        log.warning("Network error fetching %s: %s", url, e)
        return None

    code = resp.status_code
    if code in (401, 403, 451):
        log.warning(
            "Blocked (HTTP %d) fetching %s – site is refusing the request",
            code, url,
        )
        return None
    if code == 429:
        log.warning("Rate-limited (HTTP 429) fetching %s – try again later", url)
        return None
    if code >= 500:
        log.warning("Server error (HTTP %d) fetching %s", code, url)
        return None
    if code >= 400:
        log.warning("Client error (HTTP %d) fetching %s", code, url)
        return None

    try:
        return feedparser.parse(resp.content)
    except Exception as e:
        log.warning("Failed to parse feed from %s: %s", url, e)
        return None


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id              TEXT PRIMARY KEY,          -- content hash
    title           TEXT NOT NULL,
    link            TEXT NOT NULL,
    summary         TEXT,
    published_at    TEXT,                      -- ISO-8601 UTC
    source_name     TEXT,
    source_url      TEXT,
    category        TEXT,
    importance      TEXT,
    fetched_at      TEXT NOT NULL,
    raw_json        TEXT
);

CREATE INDEX IF NOT EXISTS idx_published ON articles(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_source    ON articles(source_name);
CREATE INDEX IF NOT EXISTS idx_category  ON articles(category);
"""


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def existing_ids(conn: sqlite3.Connection) -> Set[str]:
    cur = conn.execute("SELECT id FROM articles")
    return {row[0] for row in cur.fetchall()}


def insert_article(conn: sqlite3.Connection, item: dict) -> bool:
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO articles
            (id, title, link, summary, published_at, source_name, source_url,
             category, importance, fetched_at, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["id"],
                item["title"],
                item["link"],
                item["summary"],
                item["published_at"],
                item["source_name"],
                item["source_url"],
                item["category"],
                item["importance"],
                item["fetched_at"],
                json.dumps(item.get("raw", {}), ensure_ascii=False),
            ),
        )
        return True
    except sqlite3.Error as e:
        log.error("DB insert error: %s", e)
        return False


# ---------------------------------------------------------------------------
# Core ingestion
# ---------------------------------------------------------------------------
def process_feed(
    feed_cfg: dict,
    settings: dict,
    known_ids: Set[str],
    min_date: Optional[datetime] = None,
    dry_run: bool = False,
) -> List[dict]:
    name = feed_cfg["name"]
    url = feed_cfg["url"]
    category = feed_cfg.get("category", "general")
    importance = feed_cfg.get("importance", "medium")
    max_items = feed_cfg.get("max_items")

    log.info("Fetching: %s", name)
    parsed = fetch_feed(url, settings["user_agent"], settings["request_timeout"])
    if parsed is None or parsed.bozo and not parsed.entries:
        log.warning("  → empty or broken feed: %s", name)
        return []

    new_items: List[dict] = []
    entries = parsed.entries
    if max_items:
        entries = entries[:max_items]

    for entry in entries:
        title = clean_text(entry.get("title", "Untitled"))
        link = entry.get("link") or entry.get("id") or ""
        if not link:
            continue

        item_id = make_hash(title, link)
        if item_id in known_ids:
            continue

        published = parse_date(entry)
        if min_date and published and published < min_date:
            continue

        summary = clean_text(
            entry.get("summary")
            or entry.get("description")
            or entry.get("content", [{}])[0].get("value", "")
            if isinstance(entry.get("content"), list)
            else ""
        )
        # Truncate very long summaries
        if len(summary) > 1200:
            summary = summary[:1197] + "..."

        item = {
            "id": item_id,
            "title": title,
            "link": link,
            "summary": summary,
            "published_at": published.isoformat() if published else None,
            "source_name": name,
            "source_url": url,
            "category": category,
            "importance": importance,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "raw": {
                "author": entry.get("author"),
                "tags": [t.get("term") for t in entry.get("tags", []) if t.get("term")],
            },
        }
        new_items.append(item)
        known_ids.add(item_id)

    log.info("  → %d new items from %s", len(new_items), name)
    return new_items


def run_ingestion(
    config_path: Path,
    dry_run: bool = False,
    feed_filter: Optional[str] = None,
    days: Optional[int] = None,
) -> dict:
    cfg = load_config(config_path)
    settings = cfg.get("settings", {})
    feeds = [f for f in cfg.get("feeds", []) if f.get("enabled", True)]

    if feed_filter:
        feeds = [f for f in feeds if feed_filter.lower() in f["name"].lower()]
        if not feeds:
            log.error("No feed matched filter: %s", feed_filter)
            return {"new": 0, "total_fetched": 0}

    output_dir = Path(settings.get("output_dir", "./data"))
    output_dir.mkdir(parents=True, exist_ok=True)
    db_path = Path(settings.get("db_path", "./data/ai_news.db"))

    min_date = None
    if days is not None:
        min_date = datetime.now(timezone.utc) - timedelta(days=days)

    conn = None
    known_ids: Set[str] = set()
    if not dry_run:
        conn = init_db(db_path)
        known_ids = existing_ids(conn)

    all_new: List[dict] = []
    for feed in feeds:
        items = process_feed(feed, settings, known_ids, min_date=min_date, dry_run=dry_run)
        all_new.extend(items)
        time.sleep(0.8)  # polite delay

    if not dry_run and conn and all_new:
        for item in all_new:
            insert_article(conn, item)
        conn.commit()
        conn.close()
        log.info("Wrote %d new articles to %s", len(all_new), db_path)

        if settings.get("json_archive", True):
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            archive_path = output_dir / f"ingest_{stamp}.json"
            with open(archive_path, "w", encoding="utf-8") as f:
                json.dump(all_new, f, ensure_ascii=False, indent=2)
            log.info("JSON archive: %s", archive_path)

    return {
        "new": len(all_new),
        "total_fetched": len(all_new),
        "sources": len(feeds),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="AI Newsletter RSS Ingester")
    parser.add_argument(
        "--config",
        default="feeds.yaml",
        help="Path to feeds.yaml",
    )
    parser.add_argument("--dry-run", action="store_true", help="Do not write to DB")
    parser.add_argument("--feed", type=str, help="Only process feeds whose name contains this string")
    parser.add_argument("--days", type=int, help="Only keep items newer than N days")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        log.error("Config not found: %s", config_path)
        sys.exit(1)

    result = run_ingestion(
        config_path,
        dry_run=args.dry_run,
        feed_filter=args.feed,
        days=args.days,
    )
    log.info("Done. New articles: %d (from %d feeds)", result["new"], result["sources"])


if __name__ == "__main__":
    main()