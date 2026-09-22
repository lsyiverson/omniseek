#!/usr/bin/env python3
"""Normalize / merge / dedup / sort a set of Documents.

Reads one or more JSON files (each a list of Documents, or a single Document)
or reads from stdin. Outputs a single merged list.

Operations (toggle via flags):
  --merge     merge multiple input files (default on)
  --dedup     collapse duplicates by URL + title-fingerprint
  --sort      sort by (recency × source priority × query-match score)
  --filter    drop entries older than --max-age-days
  --score     compute a simple 0-1 score per entry

Examples:
    cat arxiv.json openalex.json | python3 normalize_doc.py --merge --dedup
    python3 normalize_doc.py --merge *.json --dedup --sort --max-age-days 365
    python3 normalize_doc.py --merge --filter-source hackernews --keep
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Iterable


def _load_inputs(paths: list[Path]) -> Iterable[dict]:
    for p in paths:
        if p == Path("-"):
            text = sys.stdin.read()
        else:
            try:
                text = p.read_text(encoding="utf-8")
            except FileNotFoundError:
                print(f"normalize_doc: file not found: {p}", file=sys.stderr)
                continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            print(f"normalize_doc: bad JSON in {p}: {exc}", file=sys.stderr)
            continue
        if isinstance(data, list):
            yield from data
        elif isinstance(data, dict):
            yield data


def _fingerprint(doc: dict) -> str:
    """Stable fingerprint: URL + title-alnum-lowercase.

    Used for dedup across sources (different sources may describe the same
    paper differently but URL or DOI matches).
    """
    url = (doc.get("url") or "").strip().lower()
    title = re.sub(r"\s+", " ", (doc.get("title") or "").strip().lower())
    title = re.sub(r"[^a-z0-9 ]", "", title)
    base = url or title
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16] if base else ""


def _title_tokens(doc: dict) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (doc.get("title") or "").lower()))


def _query_match(doc: dict, query_terms: list[str]) -> float:
    if not query_terms:
        return 0.0
    title_tokens = _title_tokens(doc)
    content_tokens = set(re.findall(r"[a-z0-9]+", (doc.get("content") or "").lower()))
    haystack = title_tokens | content_tokens
    hits = sum(1 for t in query_terms if t in haystack)
    return hits / len(query_terms)


def _recency(doc: dict) -> float:
    """Days-since-published clamped to [0, 1] over a 5-year horizon."""
    s = doc.get("published_at") or ""
    if not s:
        return 0.0
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        age_days = (dt.datetime.now(dt.timezone.utc) - d).days
        return max(0.0, 1.0 - min(age_days, 365 * 5) / (365 * 5))
    except Exception:
        return 0.0


# Coarse source priority — a paper or job is more "trustworthy" / better
# structured than a comment. This is intentionally simple; tweak as needed.
_SOURCE_PRIORITY = {
    "arxiv": 0.95,
    "openalex": 0.90,
    "semantic_scholar": 0.92,
    "crossref": 0.88,
    "dblp": 0.90,
    "europe_pmc": 0.85,
    "zenodo": 0.70,
    "github_repo": 0.80,
    "github_code": 0.75,
    "github_issue": 0.60,
    "github_tree": 0.65,
    "hf_daily_papers": 0.85,
    "hackernews_story": 0.55,
    "hackernews_comment": 0.35,
    "stackoverflow_question": 0.65,
    "stackoverflow_answer": 0.55,
    "reddit": 0.45,
    "bluesky": 0.45,
    "rss": 0.60,
    "smzdm": 0.65,
    "wayback": 0.40,
    "mycareersfuture": 0.85,
    "remotive": 0.75,
    "nsf_awards": 0.95,
    "nih_reporter": 0.95,
    # Walled sources — long-form answers tend to be more curated than comments;
    # bumped above the comment-only sources but below primary research papers.
    "zhihu": 0.75,
    "xiaohongshu": 0.55,
}


def _score(doc: dict, query_terms: list[str]) -> float:
    s = _recency(doc) * 0.4 + _query_match(doc, query_terms) * 0.4 + _SOURCE_PRIORITY.get(doc.get("source", ""), 0.5) * 0.2
    return round(s, 4)


def normalize(
    docs: list[dict],
    *,
    dedup: bool,
    sort: bool,
    query: str,
    max_age_days: int | None,
    drop_sources: set[str] | None = None,
) -> list[dict]:
    drop_sources = drop_sources or set()

    out: list[dict] = []
    for d in docs:
        if d.get("source") in drop_sources:
            continue
        if max_age_days is not None:
            pub = d.get("published_at")
            if pub:
                try:
                    age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(pub.replace("Z", "+00:00"))).days
                    if age > max_age_days:
                        continue
                except Exception:
                    pass
        if dedup:
            d["_fingerprint"] = _fingerprint(d)
        out.append(d)

    if dedup:
        seen: set[str] = set()
        deduped: list[dict] = []
        for d in out:
            fp = d.get("_fingerprint")
            if not fp:
                deduped.append(d)
                continue
            if fp in seen:
                continue
            seen.add(fp)
            deduped.append(d)
        out = deduped

    query_terms = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 1]

    for d in out:
        d["_score"] = _score(d, query_terms)
        # Drop the dedup marker from the final output
        d.pop("_fingerprint", None)

    if sort:
        out.sort(key=lambda d: d.get("_score", 0), reverse=True)

    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Normalize / merge / dedup / sort Documents")
    p.add_argument("files", nargs="*", type=Path, default=[], help="JSON files (each a list of Documents). '-' = stdin")
    p.add_argument("--no-merge", dest="merge", action="store_false", help="Disable merge (skip files input)")
    p.add_argument("--no-dedup", dest="dedup", action="store_false", help="Disable dedup")
    p.add_argument("--no-sort", dest="sort", action="store_false", help="Disable scoring + sort")
    p.add_argument("--max-age-days", type=int, help="Drop entries older than N days")
    p.add_argument("--filter-source", action="append", default=[], help="Drop entries with these source names (repeatable)")
    p.add_argument("--query", default="", help="Query string for relevance scoring (default: no scoring)")
    p.add_argument("--keep-score", action="store_true", help="Keep the _score field in output")
    args = p.parse_args()

    docs: list[dict] = []
    if args.merge and args.files:
        docs.extend(_load_inputs(list(args.files)))

    out = normalize(
        docs,
        dedup=args.dedup,
        sort=args.sort,
        query=args.query,
        max_age_days=args.max_age_days,
        drop_sources=set(args.filter_source),
    )

    if not args.keep_score:
        for d in out:
            d.pop("_score", None)

    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())