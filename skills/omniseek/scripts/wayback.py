#!/usr/bin/env python3
"""Wayback Machine: history of a URL — Internet Archive CDX snapshot index.

Web search returns only the LIVE page; Wayback returns every archived
snapshot. Useful for: investigating how a page changed over time, reading
content that's since been deleted or edited, comparing two versions of a
regulatory or policy page.

Docs: https://archive.org/developers/wayback-cdx-server.html
Endpoint: GET https://web.archive.org/cdx/search/cdx?url=<URL>&output=json&limit=<n>

Examples:
    python3 wayback.py "https://www.cdc.gov/quarantine/about.html" --limit 20
    python3 wayback.py "https://www.federalregister.gov" --from 2024 --to 2025 --limit 10
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

CDX = "https://web.archive.org/cdx/search/cdx"


def _http_get(url: str, timeout: int = 30) -> list | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "omniseek-mavis/0.1 (research retrieval)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"wayback.http_error: {exc}", file=sys.stderr)
        return None


def _iso_timestamp(ts: str) -> str | None:
    if not ts or len(ts) < 8:
        return None
    try:
        dt = datetime.strptime(ts[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")
    except Exception:
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def snapshots(url: str, limit: int = 20, from_: str | None = None, to_: str | None = None) -> list[dict]:
    params = {
        "url": url,
        "output": "json",
        "limit": str(min(limit, 200)),
        "fl": "timestamp,original,statuscode,mimetype,length",
        "sort": "timestamp",
        "order": "desc",
    }
    if from_:
        params["from"] = from_
    if to_:
        params["to"] = to_

    api = f"{CDX}?{urllib.parse.urlencode(params)}"
    rows = _http_get(api)
    if not rows or not isinstance(rows, list):
        return []

    # First row is the field labels
    if len(rows) < 2:
        return []

    header = rows[0]
    out = []
    for r in rows[1:]:
        rec = dict(zip(header, r))
        ts = rec.get("timestamp", "")
        archive_url = f"https://web.archive.org/web/{ts}/{rec.get('original')}" if ts else ""
        out.append({
            "source": "wayback",
            "source_id": f"{rec.get('original')}|{ts}",
            "title": f"{rec.get('original')} @ {ts[:8]}",
            "url": archive_url,
            "content": "",
            "authors": [],
            "published_at": _iso_timestamp(ts),
            "fetched_at": _now(),
            "metadata": {
                "snapshot_timestamp": ts,
                "original_url": rec.get("original"),
                "status": rec.get("statuscode"),
                "mimetype": rec.get("mimetype"),
                "length": rec.get("length"),
                "kind": "wayback_snapshot",
            },
        })
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Wayback Machine snapshot history for a URL")
    p.add_argument("url", help="URL to look up in the Internet Archive")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--from", dest="from_", help="Start year (YYYY) or YYYYMMDD")
    p.add_argument("--to", dest="to_", help="End year (YYYY) or YYYYMMDD")
    args = p.parse_args()

    docs = snapshots(args.url, limit=args.limit, from_=args.from_, to_=args.to_)
    json.dump(docs, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())