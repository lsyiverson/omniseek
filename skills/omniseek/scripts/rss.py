#!/usr/bin/env python3
"""Generic RSS / Atom feed aggregator.

Takes a list of feed URLs and returns the most recent entries as normalized
Documents. Useful for: research lab blogs, conference news, journal TOC
feeds, immigration authority updates, etc. You give it URLs; it doesn't
discover them.

The script reads the URLs from the command line or from a file
(one URL per line). Each entry is tagged with the feed's root URL so
provenance is preserved.

Examples:
    python3 rss.py https://bair.berkeley.edu/blog/feed.xml --limit 5
    python3 rss.py --file feeds.txt --limit 10
    python3 rss.py https://export.arxiv.org/rss/cs.LG https://export.arxiv.org/rss/cs.CL --limit 5
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Iterable


def _http_get(url: str, timeout: int = 20) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "omniseek-mavis/0.1 (research retrieval)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as exc:
        print(f"rss.http_error: {url}: {exc}", file=sys.stderr)
        return None


def _iso(s: str | None) -> str | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return s


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _entry_to_doc(feed_url: str, entry: ET.Element, ns: dict) -> dict:
    # RSS uses 'item'; Atom uses 'entry'
    title = (
        entry.findtext("title", default="", namespaces=ns)
        or entry.findtext("atom:title", default="", namespaces=ns)
        or ""
    ).strip()

    link = ""
    for child in list(entry):
        tag = child.tag.split("}", 1)[-1]
        if tag == "link":
            href = child.attrib.get("href")
            if href:
                link = href
                break
    if not link:
        link = (
            entry.findtext("link", default="", namespaces=ns)
            or entry.findtext("atom:link", default="", namespaces=ns)
            or ""
        )

    description = (
        entry.findtext("description", default="", namespaces=ns)
        or entry.findtext("summary", default="", namespaces=ns)
        or entry.findtext("atom:summary", default="", namespaces=ns)
        or ""
    ).strip()

    pub = (
        entry.findtext("pubDate", default=None, namespaces=ns)
        or entry.findtext("atom:published", default=None, namespaces=ns)
        or entry.findtext("atom:updated", default=None, namespaces=ns)
    )
    pub_iso = _iso(pub)

    author = (
        entry.findtext("author", default="", namespaces=ns)
        or entry.findtext("atom:author/atom:name", default="", namespaces=ns)
        or ""
    ).strip()

    guid = (
        entry.findtext("guid", default=None, namespaces=ns)
        or entry.findtext("atom:id", default=None, namespaces=ns)
        or link
    )

    return {
        "source": "rss",
        "source_id": guid,
        "title": title,
        "url": link,
        "content": description[:3000],
        "authors": [author] if author else [],
        "published_at": pub_iso,
        "fetched_at": _now(),
        "metadata": {
            "feed_url": feed_url,
            "kind": "rss_entry",
        },
    }


def fetch_feed(url: str) -> tuple[str, list[dict]]:
    """Fetch and parse a single feed. Returns (feed_url, docs)."""
    raw = _http_get(url)
    if not raw:
        return url, []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        print(f"rss.parse_error: {url}: {exc}", file=sys.stderr)
        return url, []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = root.findall(".//item") or root.findall(".//atom:entry", ns)
    return url, [_entry_to_doc(url, e, ns) for e in entries]


def aggregate(feed_urls: Iterable[str], limit_per_feed: int = 5) -> list[dict]:
    all_docs: list[dict] = []
    for url in feed_urls:
        url, docs = fetch_feed(url)
        # Sort newest first
        docs.sort(key=lambda d: d.get("published_at") or "", reverse=True)
        all_docs.extend(docs[:limit_per_feed])
    # Final sort across all feeds
    all_docs.sort(key=lambda d: d.get("published_at") or "", reverse=True)
    return all_docs


def main() -> int:
    p = argparse.ArgumentParser(description="Generic RSS/Atom feed aggregator")
    p.add_argument("urls", nargs="*", help="Feed URLs (RSS or Atom). Pass nothing if --file is used.")
    p.add_argument("--file", help="File with one feed URL per line")
    p.add_argument("--limit", type=int, default=5, help="Per-feed cap (default 5)")
    args = p.parse_args()

    urls: list[str] = list(args.urls)
    if args.file:
        with open(args.file) as f:
            urls.extend(line.strip() for line in f if line.strip() and not line.startswith("#"))

    if not urls:
        print("No feed URLs given. Pass them as positional args or via --file.", file=sys.stderr)
        return 1

    docs = aggregate(urls, limit_per_feed=args.limit)
    json.dump(docs, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())