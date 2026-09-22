#!/usr/bin/env python3
"""Bluesky: public AT Protocol post search (the open Twitter alternative).

Bluesky's public API (jetstream + the indexed search endpoint) is open. This
script searches posts (not profiles) by free text. Useful for tech + academia
discussion that's outside the walled-garden Twittersphere.

Docs: https://docs.bsky.app
Endpoint: GET https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?q=<query>&limit=<n>

Examples:
    python3 bluesky.py "transformer attention" --limit 20
    python3 bluesky.py "PhD application" --since 24h --limit 30
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ENDPOINT = "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts"


def _http_get(url: str, timeout: int = 20) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "omniseek/0.1 (research retrieval)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"bluesky.http_error: {exc}", file=sys.stderr)
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _doc_from_post(post: dict) -> dict:
    record = post.get("record") or {}
    author = post.get("author") or {}
    embed = record.get("embed") or {}
    embed_record = (embed.get("record") or {}).get("value") if isinstance(embed.get("record"), dict) else None

    text = (record.get("text") or "") + (
        ("\n\n[embed: " + (embed_record.get("text") or "") + "]" if embed_record and embed_record.get("text") else "")
    )

    return {
        "source": "bluesky",
        "source_id": post.get("cid") or (post.get("uri") or ""),
        "title": (text or "").split("\n")[0][:140],
        "url": (post.get("author") or {}).get("handle", "") and f"https://bsky.app/profile/{post['author']['handle']}/post/{post.get('uri', '').rsplit('/', 1)[-1]}" or "",
        "content": text,
        "authors": [author.get("display_name") or author.get("handle")] if author else [],
        "published_at": (record.get("createdAt")),
        "fetched_at": _now(),
        "metadata": {
            "handle": author.get("handle"),
            "did": author.get("did"),
            "lang": record.get("langs") or [],
            "like_count": post.get("likeCount"),
            "repost_count": post.get("repostCount"),
            "reply_count": post.get("replyCount"),
            "quote_count": post.get("quoteCount"),
            "indexed_at": post.get("indexedAt"),
        },
    }


def search(query: str, limit: int = 10, since: str | None = None) -> list[dict]:
    params = {
        "q": query,
        "limit": str(min(limit, 50)),
    }
    if since:
        params["since"] = since
    url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"
    data = _http_get(url)
    if not isinstance(data, dict):
        return []
    return [_doc_from_post(p) for p in (data.get("posts") or [])]


def main() -> int:
    p = argparse.ArgumentParser(description="Bluesky public post search")
    p.add_argument("query", help="Free-text search query")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--since", help="Time bound (e.g. '24h', '7d'); passed through to Bluesky")
    args = p.parse_args()

    docs = search(args.query, limit=args.limit, since=args.since)
    json.dump(docs, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())