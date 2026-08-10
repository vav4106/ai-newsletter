#!/usr/bin/env python3
"""
Quick query helper for the AI news SQLite database.

Examples:
    python query_db.py --today
    python query_db.py --date 2026-03-24
    python query_db.py --source OpenAI --limit 10
    python query_db.py --important
    python query_db.py --search "transformer"
"""

import argparse
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "ai_news.db"


def get_conn():
    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}\nRun ingest_rss.py first.")
    return sqlite3.connect(str(DB_PATH))


def main():
    parser = argparse.ArgumentParser(description="Query AI news DB")
    parser.add_argument("--today", action="store_true")
    parser.add_argument("--date", type=str, help="YYYY-MM-DD")
    parser.add_argument("--source", type=str)
    parser.add_argument("--category", type=str)
    parser.add_argument("--important", action="store_true", help="importance = high")
    parser.add_argument("--search", type=str, help="Search title/summary")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    conn = get_conn()
    conditions = []
    params = []

    if args.today:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        conditions.append("date(published_at) = ?")
        params.append(today)
    elif args.date:
        conditions.append("date(published_at) = ?")
        params.append(args.date)

    if args.source:
        conditions.append("source_name LIKE ?")
        params.append(f"%{args.source}%")
    if args.category:
        conditions.append("category = ?")
        params.append(args.category)
    if args.important:
        conditions.append("importance = 'high'")
    if args.search:
        conditions.append("(title LIKE ? OR summary LIKE ?)")
        params.extend([f"%{args.search}%", f"%{args.search}%"])

    where = " AND ".join(conditions) if conditions else "1=1"
    sql = f"""
        SELECT title, link, published_at, source_name, category, importance, summary
        FROM articles
        WHERE {where}
        ORDER BY published_at DESC NULLS LAST
        LIMIT ?
    """
    params.append(args.limit)

    cur = conn.execute(sql, params)
    rows = cur.fetchall()
    conn.close()

    if args.json:
        keys = ["title", "link", "published_at", "source_name", "category", "importance", "summary"]
        print(json.dumps([dict(zip(keys, r)) for r in rows], indent=2, ensure_ascii=False))
    else:
        print(f"Found {len(rows)} articles\n" + "-" * 60)
        for r in rows:
            title, link, pub, source, cat, imp, summary = r
            print(f"[{pub or 'no-date'}] ({source} | {cat} | {imp})")
            print(f"  {title}")
            print(f"  {link}")
            if summary:
                print(f"  {summary[:180]}…")
            print()


if __name__ == "__main__":
    main()