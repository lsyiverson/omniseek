#!/usr/bin/env python3
"""什么值得买 — original-content (值客原创) RSS feed.

什么值得买 runs a public RSS feed for its 原创频道 / 值客原创 at
``https://post.smzdm.com/feed`` — no auth, no fingerprint challenge, no
rate limit (other than polite HTTP). Each item is a long-form user post:
晒物, 评测, 攻略, 消费知识, 摄影, 生活记录.

Because smzdm's search endpoint is JS-fingerprint gated and the public
mobile site returns 404 for search, we expose this RSS feed as the
**free, keyless retrieval path**. We don't have a true search parameter,
so keyword matching is done client-side after fetching the feed (which
contains the latest ~30 items).

This complements 知乎 / 小红书 (walled, login-required) for Chinese
consumer-product intelligence — useful for "sweep" / "structure" steps
in the sweep → zoom → structure workflow:

    sweep prices/researchers

Examples:
    # Latest original posts (any category)
    python3 smzdm.py --limit 20

    # Keyword filter — matches title / description / category (case-insensitive)
    python3 smzdm.py --keyword 机械键盘 --limit 10
    python3 smzdm.py --keyword 显卡 --limit 5

    # Filter by 频道
    python3 smzdm.py --category 电脑数码 --limit 15
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


FEED_URL = "https://post.smzdm.com/feed"
USER_AGENT = "omniseek/0.1 (research retrieval)"
DEFAULT_LIMIT = 20


def _http_get(url: str, timeout: int = 20) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as exc:
        print(f"smzdm.http_error: {url}: {exc}", file=sys.stderr)
        return None


def _looks_like_captcha(payload: bytes | str) -> bool:
    """smzdm serves a Tencent captcha interstitial when the request fingerprint
    is suspect (too many requests, datacenter IP, missing browser signals, …).
    Detect it so callers get a clear message instead of a parse error."""
    if isinstance(payload, bytes):
        head = payload[:2000].decode("utf-8", errors="ignore")
    else:
        head = payload[:2000]
    return ("TCaptcha" in head) or ("TencentCaptcha" in head) or ("captcha.show" in head)


def _strip_html(s: str) -> str:
    """Drop tags + collapse whitespace. We keep description lightweight so the
    Document envelope stays small; full HTML stays in metadata.full_content_html."""
    if not s:
        return ""
    # CDATA wrapper -> unwrap
    s = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", s, flags=re.DOTALL)
    # Drop script/style blocks entirely (defensive — RSS doesn't usually have them)
    s = re.sub(r"<(script|style)\b.*?</\1>", " ", s, flags=re.DOTALL | re.IGNORECASE)
    # Strip remaining tags
    s = re.sub(r"<[^>]+>", " ", s)
    # Decode common entities
    s = (
        s.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _iso(s: str | None) -> str | None:
    if not s:
        return None
    try:
        # RSS pubDate is RFC-822 ("Mon, 21 Sep 2026 09:06:20 +0800")
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return s


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _entry_to_doc(entry: ET.Element) -> dict:
    title = (entry.findtext("title", default="") or "").strip()
    link = (entry.findtext("link", default="") or "").strip()
    description_raw = entry.findtext("description", default="") or ""
    content_raw = ""
    for child in entry:
        tag = child.tag.split("}", 1)[-1]
        if tag == "encoded":
            content_raw = child.text or ""
            break
    author = (entry.findtext("author", default="") or "").strip()
    source = ""
    for child in entry:
        tag = child.tag.split("}", 1)[-1]
        if tag == "source":
            # <source url="...">什么值得买</source>
            source = (child.text or "").strip()
            break
    category = (entry.findtext("category", default="") or "").strip()
    pub_raw = entry.findtext("pubDate", default="")

    description_clean = _strip_html(description_raw)
    content_clean = _strip_html(content_raw)

    return {
        "source": "smzdm",
        "source_id": link,
        "title": title,
        "url": link,
        # Primary content = description (lead paragraph); the user can read full
        # article by visiting the URL or via metadata.full_content.
        "content": description_clean[:3000],
        "authors": [author] if author else [],
        "published_at": _iso(pub_raw),
        "fetched_at": _now(),
        "metadata": {
            "kind": "smzdm_post",
            "feed_url": FEED_URL,
            "category": category,
            "publisher": source or "什么值得买",
            "full_content": content_clean[:8000] if content_clean else None,
        },
    }


def fetch_feed(url: str = FEED_URL) -> list[dict]:
    """Fetch and parse the public RSS feed. Returns a list of Documents."""
    raw = _http_get(url)
    if not raw:
        return []
    if _looks_like_captcha(raw):
        print(
            "smzdm.gated: RSS endpoint is serving a Tencent captcha interstitial. "
            "smzdm.com has started gating all unauthenticated traffic (verified late 2025 / 2026). "
            "Retry from a residential IP, or wait — the block usually clears within a few hours. "
            "If you need persistent access, route the request through your logged-in Chrome via CDP "
            "(see references/walled.md).",
            file=sys.stderr,
        )
        return []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        print(f"smzdm.parse_error: {url}: {exc}", file=sys.stderr)
        return []
    entries = root.findall(".//item")
    return [_entry_to_doc(e) for e in entries]


def filter_docs(
    docs: list[dict],
    *,
    keyword: str | None,
    category: str | None,
    limit: int,
) -> list[dict]:
    """Sort newest first, apply keyword / category filter, cap to limit."""
    # Sort newest first (RSS is already newest-first, but be defensive)
    docs.sort(key=lambda d: d.get("published_at") or "", reverse=True)

    if keyword:
        kw = keyword.lower()
        kept = []
        for d in docs:
            haystack = " ".join(
                [
                    (d.get("title") or "").lower(),
                    (d.get("content") or "").lower(),
                    ((d.get("metadata") or {}).get("category") or "").lower(),
                ]
            )
            if kw in haystack:
                kept.append(d)
        docs = kept

    if category:
        kept = []
        for d in docs:
            if (d.get("metadata") or {}).get("category") == category:
                kept.append(d)
        docs = kept

    return docs[:limit]


def main() -> int:
    p = argparse.ArgumentParser(
        description="什么值得买 (smzdm.com) original-content RSS — public feed, no auth",
    )
    # Accept query as positional too (so `multi_search.py` can call us like the
    # other scripts). When given, it acts as the --keyword filter.
    p.add_argument("query", nargs="?", help="Substring filter (alias for --keyword)")
    p.add_argument("--keyword", help="Substring filter against title / description / category (case-insensitive)")
    p.add_argument("--category", help="Restrict to one 频道 (e.g. 电脑数码, 家用电器)")
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"Max items to return (default {DEFAULT_LIMIT})")
    p.add_argument("--feed-url", default=FEED_URL, help="Override the RSS feed URL (advanced)")
    args = p.parse_args()

    keyword = args.keyword or args.query

    docs = fetch_feed(args.feed_url)
    if not docs:
        # Stderr already explained why. Return [] with exit 0 — empty result is
        # not an error per the skill's output contract.
        print("[]")
        return 0

    docs = filter_docs(
        docs,
        keyword=keyword,
        category=args.category,
        limit=args.limit,
    )
    json.dump(docs, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())