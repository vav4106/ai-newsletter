# AI Newsletter – RSS Ingestion System

Automated daily ingestion of AI news from major official sources.

## Files

| File | Purpose |
|------|---------|
| `feeds.yaml` | Feed list + settings (edit this to add/remove sources) |
| `ingest_rss.py` | Main ingestion script |
| `scheduler.py` | Daily scheduler (runs ingest at a fixed UTC time) |
| `query_db.py` | Simple CLI to query the SQLite database |
| `data/ai_news.db` | SQLite database of all ingested articles |
| `data/ingest_*.json` | Timestamped JSON archives of each run |

## Quick Start

```bash
cd ingestion
pip install -r requirements.txt

# One-shot ingestion (last 30 days of items that the feeds expose)
python ingest_rss.py --days 30

# Dry-run (no DB write)
python ingest_rss.py --dry-run

# Only one source
python ingest_rss.py --feed "OpenAI"

# Query the database
python query_db.py --today
python query_db.py --important --limit 15
python query_db.py --date 2026-08-06
python query_db.py --search "GPT" --json
```

## Daily Automation

```bash
# Run once immediately then every day at 06:00 UTC
python scheduler.py --hour 6 --minute 0

# Or run once and exit
python scheduler.py --once
```

Recommended production options:

- **cron**: `0 6 * * * cd /path/to/ingestion && python ingest_rss.py`
- **systemd timer**
- **GitHub Actions** scheduled workflow
- **Docker + cron**

## Database Schema

```sql
articles (
  id           TEXT PRIMARY KEY,   -- SHA-256 content hash
  title        TEXT,
  link         TEXT,
  summary      TEXT,
  published_at TEXT,               -- ISO-8601 UTC
  source_name  TEXT,
  source_url   TEXT,
  category     TEXT,               -- company | research | industry | …
  importance   TEXT,               -- high | medium | low
  fetched_at   TEXT,
  raw_json     TEXT
)
```

## Adding New Feeds

Edit `feeds.yaml`:

```yaml
- name: Your Source
  url: https://example.com/feed.xml
  category: research
  importance: medium
  enabled: true
  max_items: 20   # optional
```

## Anthropic scraper (no official RSS)

Anthropic does not publish an RSS feed. Use the dedicated scraper:

```bash
python scrape_anthropic.py
python scrape_anthropic.py --dry-run
python scrape_anthropic.py --days 90
```

It parses https://www.anthropic.com/news, extracts title / date / link / short summary,
deduplicates against the same SQLite DB, and marks items as `importance = high`.

### Full article bodies

```bash
python fetch_bodies.py                     # fill missing bodies
python fetch_bodies.py --source Anthropic  # Anthropic only
python fetch_bodies.py --limit 20 --dry-run
python fetch_bodies.py --force             # re-fetch existing bodies
```

Adds a `body` column and populates it by scraping the article page.
Also improves empty/short `summary` fields from the first ~400 characters of the body.

**Working well:** Anthropic (avg ~9k chars).  
**Blocked / limited:** OpenAI returns 403 (bot protection) – handled gracefully:
  - Domain added to an in-memory block list for the rest of the run
  - `fetch_status = 'blocked_403'` stored so future runs skip those rows
  - No repeated requests to the blocked host  
**arXiv:** abstracts only (already present in RSS).

`fetch_status` values: `ok` | `blocked_403` | `blocked_429` | `error` | `empty`

The daily scheduler runs: RSS → Anthropic scrape → body enrichment.

Other sources without reliable public RSS (xAI, Mistral, Meta AI, NVIDIA AI Blog)
can be added later with similar scrapers.

## Next Integration Steps for the Website

1. Expose a simple JSON API (or use the SQLite file directly from a backend).
2. On the frontend calendar / “Today’s AI News” page, query by `published_at` date.
3. Mark selected historical milestones as `importance = high` and pin them in the right-hand “Important AI Dates” sidebar.
4. Weekly digest: query last 7 days ordered by importance + recency and send via Resend / Buttondown.

## Current Sources (working as of Aug 2026)

- OpenAI News
- Google DeepMind
- Google AI Blog
- Hugging Face Blog
- TechCrunch AI
- MIT Technology Review AI
- The Verge AI
- arXiv cs.AI (capped at 30 items per run)

VentureBeat and MarkTechPost may need URL updates if their feeds change.