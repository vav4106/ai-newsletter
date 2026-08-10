#!/usr/bin/env python3
"""
Simple daily scheduler for the RSS ingestion script.
Run this as a long-lived process or under systemd / Docker.

Example:
    python scheduler.py
    # or
    python scheduler.py --hour 6 --minute 30   # run every day at 06:30 UTC
"""

import argparse
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import schedule

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("scheduler")

SCRIPT_DIR = Path(__file__).resolve().parent


def run_script(script_name: str, label: str, extra_args: list | None = None):
    script = SCRIPT_DIR / script_name
    cmd = [sys.executable, str(script)]
    if extra_args:
        cmd.extend(extra_args)
    log.info("Starting %s…", label)
    try:
        result = subprocess.run(
            cmd,
            cwd=str(SCRIPT_DIR),
            capture_output=True,
            text=True,
            timeout=900,
        )
        if result.returncode == 0:
            log.info("%s finished successfully", label)
            if result.stdout:
                for line in result.stdout.strip().splitlines()[-6:]:
                    log.info("  %s", line)
        else:
            log.error("%s failed (code %d)", label, result.returncode)
            if result.stderr:
                log.error(result.stderr[-400:])
    except Exception as e:
        log.exception("%s error: %s", label, e)


def job():
    run_script("ingest_rss.py", "RSS ingestion")
    run_script("scrape_anthropic.py", "Anthropic scraper")
    # Enrich thin articles (esp. Anthropic) with full page bodies
    run_script(
        "fetch_bodies.py",
        "Body fetcher (Anthropic)",
        extra_args=["--source", "Anthropic", "--limit", "30", "--delay", "1.0"],
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hour", type=int, default=6, help="UTC hour to run daily (0-23)")
    parser.add_argument("--minute", type=int, default=0, help="UTC minute")
    parser.add_argument("--once", action="store_true", help="Run once immediately and exit")
    args = parser.parse_args()

    if args.once:
        job()
        return

    schedule.every().day.at(f"{args.hour:02d}:{args.minute:02d}").do(job)
    log.info("Scheduler started – will run daily at %02d:%02d UTC", args.hour, args.minute)
    log.info("Press Ctrl+C to stop")

    # Also run once on startup
    job()

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()