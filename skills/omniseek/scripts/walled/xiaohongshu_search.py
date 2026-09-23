#!/usr/bin/env python3
"""Xiaohongshu (小红书) discovery search via the persistent logged-in Chrome on port 9223.

Connects to the dedicated xiaohongshu Chrome (separate from the shared
9222 one — accounts/anti-bot posture is different). Drives the discovery
page search box (NOT the explore page), waits for the result grid to
hydrate, and parses the rendered note cards.

Prerequisites:
    pip install playwright beautifulsoup4
    scripts/launch_browser.sh 9223 ~/.omniseek/chrome-9223 https://www.xiaohongshu.com
        # log in by hand in the window

Note: ``playwright install chromium`` is OPTIONAL. This script uses
``connect_over_cdp`` (remote attach), not ``launch()`` (local spawn), so
playwright only needs the Python package. If you already have Google
Chrome / Chromium installed locally, just run ``launch_browser.sh`` and
skip the ``playwright install chromium`` step. Only run that step if you
have no local Chrome at all.

Examples:
    python3 scripts/walled/xiaohongshu_search.py "PhD 申请 香港" --limit 10
    python3 scripts/walled/xiaohongshu_search.py "字节跳动 面经" --limit 5
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _cdp import cdp_call, cdp_health  # noqa: E402

try:
    from bs4 import BeautifulSoup  # type: ignore
except ImportError:
    BeautifulSoup = None  # type: ignore

PORT = 9223
SEARCH_URL = "https://www.xiaohongshu.com/search_result?keyword={q}&source=web_explore_feed"

# Note card selectors (measured against the live site, late 2025 / 2026):
#   section.note-item                 the card root
#   .footer .author                   author display name
#   a.cover.ld.mask                   the note link + thumbnail
#   .title span, .title               title text
#   .time, .date                      publication time (often "MM-DD" or "刚刚")
_NOTE_SEL = "section.note-item, .note-item"
_TITLE_SEL = ".title span, .title"
_AUTHOR_SEL = ".footer .author, .author"
_TIME_SEL = ".footer .time, .time, .date"
_COVER_A_SEL = "a.cover"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _flow(page, query: str, limit: int) -> list[dict]:
    page.wait_for_selector(_NOTE_SEL, timeout=15000)
    # Scroll to trigger lazy hydration
    for y in (200, 600, 1200, 1800):
        page.evaluate(f"window.scrollTo(0, {y})")
        page.wait_for_timeout(900)
    return _parse_html(page.content(), query, limit)


def _parse_html(html: str, query: str, limit: int) -> list[dict]:
    if BeautifulSoup is None:
        print("walled/xiaohongshu_search: beautifulsoup4 not installed; pip install beautifulsoup4", file=sys.stderr)
        return []
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(_NOTE_SEL)
    docs: list[dict] = []
    for card in cards[:limit]:
        a = card.select_one(_COVER_A_SEL)
        href = a.get("href") or a.get("data-href") if a else None
        if not href:
            continue
        if href.startswith("/"):
            href = "https://www.xiaohongshu.com" + href

        title_el = card.select_one(_TITLE_SEL)
        title = title_el.get_text(strip=True) if title_el else ""

        author_el = card.select_one(_AUTHOR_SEL)
        author = author_el.get_text(strip=True) if author_el else None

        time_el = card.select_one(_TIME_SEL)
        time_text = time_el.get_text(strip=True) if time_el else None

        note_id = href.rsplit("/", 1)[-1].split("?")[0]

        docs.append({
            "source": "xiaohongshu",
            "source_id": note_id,
            "title": title or "(untitled)",
            "url": href,
            "content": "",  # snippet only — full text requires omniseek_read
            "authors": [author] if author else [],
            "published_at": None,  # raw text only; consumer can parse "MM-DD" / "刚刚"
            "fetched_at": _now(),
            "metadata": {
                "kind": "walled_search_result",
                "platform": "xiaohongshu.com",
                "query": query[:60],
                "time_text": time_text,
                "note_type": "discovery_grid",
            },
        })
    return docs


def search(query: str, limit: int = 10) -> list[dict]:
    ok, msg = cdp_health(PORT)
    if not ok:
        print(f"walled/xiaohongshu_search: {msg}", file=sys.stderr)
        return []
    return cdp_call(
        port=PORT,
        callback=lambda page: _flow(page, query, limit),
        initial_url=SEARCH_URL.format(q=query),
        timeout_ms=20000,
    )


def main() -> int:
    p = argparse.ArgumentParser(description="Xiaohongshu (小红书) discovery search via CDP (port 9223)")
    p.add_argument("query", help="Search query")
    p.add_argument("--limit", type=int, default=10)
    args = p.parse_args()

    docs = search(args.query, limit=args.limit)
    json.dump(docs, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())