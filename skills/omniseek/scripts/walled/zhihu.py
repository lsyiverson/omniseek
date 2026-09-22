#!/usr/bin/env python3
"""Zhihu: search via the persistent logged-in Chrome on port 9222.

Connects to the shared Chrome instance (the same one you'll log into for
一亩三分地 / Discord communities / other CN forums). Search results are
server-rendered + lightly hydrated; the SearchResult cards are stable
selectors so a single page.content() + BeautifulSoup walk is enough.

Prerequisites:
    pip install playwright beautifulsoup4
    scripts/launch_browser.sh 9222   # then log in to zhihu.com in the window

Note: ``playwright install chromium`` is OPTIONAL. This script uses
``connect_over_cdp`` (remote attach), not ``launch()`` (local spawn), so
playwright only needs the Python package. If you already have Google
Chrome / Chromium installed locally, just run ``launch_browser.sh`` and
skip the ``playwright install chromium`` step. Only run that step if you
have no local Chrome at all.

Examples:
    python3 scripts/walled/zhihu.py "PhD 申请 流程" --limit 5
    python3 scripts/walled/zhihu.py "transformer 综述" --limit 10
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Use scripts/_cdp.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _cdp import cdp_call, cdp_health  # noqa: E402

try:
    from bs4 import BeautifulSoup  # type: ignore
except ImportError:
    BeautifulSoup = None  # type: ignore

PORT = 9222
SEARCH_URL = "https://www.zhihu.com/search?type=content&q={q}"

# Author + date selectors lifted from the upstream adapter (measured on live
# logged-in Chrome, 2026-08-30). The 知乎 search page renders content cards
# with a stable structure:
#   .SearchResult-Card     the card root
#   .RichContent-inner b   the author's display name (rendered in bold)
#   .SearchItem-time       the publication date (MM-DD or YYYY-MM-DD)
#   h2.ContentItem-title a title + link
#   .RichText              excerpt
_AUTHOR_TAG_SEL = ".RichContent-inner b, .CopyrightRichText-richText b, .RichText b"
_DATE_SEL = ".SearchItem-time"
_TITLE_LINK_SEL = "h2.ContentItem-title a, h2 a"
_EXCERPT_SEL = ".RichText, .RichContent-inner"
_CARD_SEL = ".SearchResult-Card"

_NOT_AUTHOR = {
    "结论", "注", "注意", "例", "例如", "问", "答", "总结", "背景", "方法", "实验",
    "摘要", "前言", "引言", "定义", "题目", "问题", "答案", "提示", "警告", "更新",
    "第一步", "第二步", "第三步", "原文", "译文", "来源", "参考", "声明", "免责声明",
}
_AUTHOR_PREFIX = re.compile(r"^([^：:，。！？；、（）()]{1,24})[：:]\s*")


def _split_author_prefix(excerpt: str) -> tuple[str | None, str]:
    m = _AUTHOR_PREFIX.match(excerpt or "")
    if not m:
        return None, excerpt
    name = m.group(1).strip()
    if not name or name in _NOT_AUTHOR:
        return None, excerpt
    return name, excerpt[m.end():]


def _card_author(card, excerpt: str) -> tuple[str | None, str]:
    b = card.select_one(_AUTHOR_TAG_SEL)
    if b:
        name = b.get_text(strip=True)
        if name and len(name) <= 40:
            rest = re.sub(r"^" + re.escape(name) + r"\s*[：:]?\s*", "", excerpt)
            return name, rest
    return _split_author_prefix(excerpt)


def _card_date(text: str | None) -> str | None:
    """Resolve abbreviated MM-DD against the current year."""
    if not text:
        return None
    text = text.strip()
    # YYYY-MM-DD or YYYY-MM or YYYY
    m = re.match(r"(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", text)
    if m:
        y, mo, dd = int(m.group(1)), int(m.group(2) or 1), int(m.group(3) or 1)
        return f"{y:04d}-{mo:02d}-{dd:02d}T00:00:00Z"
    # MM-DD (assume current year)
    m = re.match(r"(\d{1,2})-(\d{1,2})", text)
    if m:
        now = datetime.now(timezone.utc)
        mo, dd = int(m.group(1)), int(m.group(2))
        try:
            d = datetime(now.year, mo, dd, tzinfo=timezone.utc)
            if d > now:
                d = datetime(now.year - 1, mo, dd, tzinfo=timezone.utc)
            return d.isoformat().replace("+00:00", "Z")
        except ValueError:
            return None
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _flow(page, query: str, limit: int) -> list[dict]:
    """Run inside the browser: wait for results and return parsed HTML."""
    page.wait_for_selector(_CARD_SEL, timeout=15000)
    # A short scroll triggers any lazy hydration
    page.evaluate("window.scrollTo(0, 200)")
    page.wait_for_timeout(800)
    html = page.content()
    return _parse_html(html, query, limit)


def _parse_html(html: str, query: str, limit: int) -> list[dict]:
    if BeautifulSoup is None:
        print("walled/zhihu: beautifulsoup4 not installed; pip install beautifulsoup4", file=sys.stderr)
        return []
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(_CARD_SEL)
    docs: list[dict] = []
    for card in cards[:limit]:
        link = card.select_one(_TITLE_LINK_SEL)
        if not link:
            continue
        title = link.get_text(strip=True)
        href = link.get("href") or ""
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = "https://www.zhihu.com" + href

        excerpt_el = card.select_one(_EXCERPT_SEL)
        excerpt = excerpt_el.get_text(strip=True) if excerpt_el else ""
        author, excerpt = _card_author(card, excerpt)

        date_text_el = card.select_one(_DATE_SEL)
        date_text = date_text_el.get_text(strip=True) if date_text_el else None
        published = _card_date(date_text)

        doc_id = href.rsplit("/", 1)[-1].split("?")[0] if href else title

        docs.append({
            "source": "zhihu",
            "source_id": doc_id,
            "title": title,
            "url": href,
            "content": excerpt[:3000],
            "authors": [author] if author else [],
            "published_at": published,
            "fetched_at": _now(),
            "metadata": {
                "kind": "walled_search_result",
                "platform": "zhihu.com",
                "query": query[:60],
                "card_date_text": date_text,
                "author_extracted_via": "tag" if author and card.select_one(_AUTHOR_TAG_SEL) else "prefix_guess",
            },
        })
    return docs


def search(query: str, limit: int = 10) -> list[dict]:
    ok, msg = cdp_health(PORT)
    if not ok:
        print(f"walled/zhihu: {msg}", file=sys.stderr)
        return []
    initial = SEARCH_URL.format(q=query)  # urllib.parse.quote handled by Playwright
    return cdp_call(
        port=PORT,
        callback=lambda page: _flow(page, query, limit),
        initial_url=initial,
        timeout_ms=20000,
    )


def main() -> int:
    p = argparse.ArgumentParser(description="Zhihu search via CDP (port 9222)")
    p.add_argument("query", help="Search query")
    p.add_argument("--limit", type=int, default=10)
    args = p.parse_args()

    docs = search(args.query, limit=args.limit)
    json.dump(docs, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())