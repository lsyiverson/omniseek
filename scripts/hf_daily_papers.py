#!/usr/bin/env python3
"""Hugging Face Daily Papers: community-curated daily ML papers.

The HF community votes on arxiv papers each day; the daily page lists them
with upvotes, AI summary, github repo links, and comments. This is a
CURATED lens on top of arxiv — humans + AI have flagged the paper.

Docs: https://huggingface.co/api/daily-papers
Endpoint: GET https://huggingface.co/api/daily-papers?date=YYYY-MM-DD

Without ``--date``, fetches today + previous 1 day to ensure coverage.

Examples:
    python3 hf_daily_papers.py "" --limit 20
    python3 hf_daily_papers.py "" --date 2025-06-01 --limit 30
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ENDPOINT = "https://huggingface.co/api/daily-papers"


def _http_get(url: str, timeout: int = 20) -> list | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "omniseek-mavis/0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"hf_daily_papers.http_error: {exc}", file=sys.stderr)
        return None


def _doc_from_entry(e: dict) -> dict:
    paper = e.get("paper") or {}
    title = (paper.get("title") or "").strip()
    paper_id = paper.get("id") or paper.get("arxiv_id") or ""
    fetched_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    return {
        "source": "hf_daily_papers",
        "source_id": paper_id or paper.get("doi") or "",
        "title": title,
        "url": f"https://arxiv.org/abs/{paper_id}" if paper_id else (paper.get("url") or ""),
        "content": paper.get("summary", ""),
        "authors": [a.get("name") for a in (paper.get("authors") or []) if a.get("name")],
        "published_at": _iso(e.get("publishedAt") or paper.get("publishedAt")),
        "fetched_at": fetched_at,
        "metadata": {
            "arxiv_id": paper_id,
            "upvotes": e.get("paper", {}).get("upvotes") or paper.get("upvotes"),
            "github_repo": (paper.get("githubRepo") or {}).get("name") if isinstance(paper.get("githubRepo"), dict) else paper.get("githubRepo"),
            "github_stars": (paper.get("githubRepo") or {}).get("stars") if isinstance(paper.get("githubRepo"), dict) else None,
            "submitted_at": _iso(e.get("publishedAt")),
            "discussion": e.get("discussion", []),
            "thumbnail_url": paper.get("thumbnailUrl"),
            "ai_summary": paper.get("ai_summary"),
            "submitted_by": (e.get("submittedBy") or {}).get("fullname") if isinstance(e.get("submittedBy"), dict) else None,
        },
    }


def _iso(s: str | None) -> str | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return s


def fetch_day(date_str: str | None = None) -> list[dict]:
    url = ENDPOINT
    if date_str:
        url = f"{ENDPOINT}?date={date_str}"
    data = _http_get(url)
    if not isinstance(data, list):
        return []
    return [_doc_from_entry(e) for e in data]


def main() -> int:
    p = argparse.ArgumentParser(description="Hugging Face Daily Papers — community-curated ML papers")
    p.add_argument("query", help="Ignored; daily papers are a stream, not a search. Pass empty string.")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--date", help="YYYY-MM-DD; default = today + yesterday")
    args = p.parse_args()

    if args.date:
        docs = fetch_day(args.date)
    else:
        today = datetime.now(timezone.utc).date()
        days = [today, today - timedelta(days=1)]
        docs = []
        for d in days:
            docs.extend(fetch_day(d.isoformat()))

    json.dump(docs[: args.limit], sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())