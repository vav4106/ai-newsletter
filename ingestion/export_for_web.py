#!/usr/bin/env python3
"""
Export SQLite articles + existing milestones into web/data.json
for the static frontend.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "ai_news.db"
WEB_DATA = ROOT.parent / "web" / "data.json"


def load_milestones() -> list:
    """Keep milestones already curated in data.json (do not wipe them)."""
    if not WEB_DATA.exists():
        return []
    try:
        existing = json.loads(WEB_DATA.read_text(encoding="utf-8"))
        return existing.get("milestones") or []
    except Exception:
        return []


def export(limit: int = 150, days: int | None = None) -> Path:
    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    sql = """
        SELECT
            id,
            title,
            link,
            summary,
            published_at,
            source_name AS source,
            category,
            importance,
            substr(COALESCE(body, ''), 1, 600) AS body_preview
        FROM articles
        WHERE 1=1
    """
    params: list = []
    if days:
        sql += " AND date(published_at) >= date('now', ?)"
        params.append(f"-{int(days)} days")
    sql += " ORDER BY published_at DESC LIMIT ?"
    params.append(int(limit))

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    articles = []
    for r in rows:
        articles.append(
            {
                "id": r["id"],
                "title": r["title"] or "",
                "link": r["link"] or "",
                "summary": (r["summary"] or "")[:800],
                "published_at": r["published_at"] or "",
                "source": r["source"] or "",
                "category": r["category"] or "",
                "importance": r["importance"] or "normal",
                "body_preview": r["body_preview"] or "",
            }
        )

    milestones = load_milestones()

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "articles": articles,
        "milestones": milestones,
    }

    WEB_DATA.parent.mkdir(parents=True, exist_ok=True)
    WEB_DATA.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Exported {len(articles)} articles + {len(milestones)} milestones → {WEB_DATA}")
    return WEB_DATA


def main():
    p = argparse.ArgumentParser(description="Export DB → web/data.json")
    p.add_argument("--limit", type=int, default=150, help="Max articles")
    p.add_argument("--days", type=int, default=None, help="Only last N days")
    args = p.parse_args()
    export(limit=args.limit, days=args.days)


if __name__ == "__main__":
    main()
