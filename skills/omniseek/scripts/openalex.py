#!/usr/bin/env python3
"""OpenAlex: open academic graph (250M+ scholarly works, institutions, concepts).

Open alternative to Microsoft Academic / Scopus. Free, keyless, with a polite
pool that gives a faster lane to requests including a ``mailto=`` in the
User-Agent (set via the ``OMNISEEK_CONTACT_EMAIL`` env var or the standard
``OPENALEX_MAILTO`` env var).

Docs: https://docs.openalex.org
Key endpoints:
  GET /works?search=<query>&per-page=<n>          — full-text search
  GET /works?filter=from_publication_date:...,...  — filter expression

The script also accepts OpenAlex-style inline filters in the query:
  from_publication_date:2024-01-01 diffusion
  institutions.id:I136199984 llm
  type:article
  language:zh
Allowlist (anything else stays in the free-text ``search`` field).

Examples:
    python3 openalex.py "transformer attention" --limit 5
    python3 openalex.py "from_publication_date:2024-01-01 llm alignment" --limit 10
    python3 openalex.py "machine learning" --type article --limit 20
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ENDPOINT = "https://api.openalex.org/works"

_FILTER_KEYS = (
    "from_publication_date",
    "to_publication_date",
    "publication_year",
    "institutions.id",
    "institutions.ror",
    "institutions.country_code",
    "authorships.institutions.id",
    "author.id",
    "concepts.id",
    "primary_topic.id",
    "type",
    "is_oa",
    "language",
)
_FILTER_RE = re.compile(
    r"(?:^|\s)(" + "|".join(re.escape(k) for k in _FILTER_KEYS) + r"):([^\s,]+)",
    re.IGNORECASE,
)


def _parse_filters(query: str) -> tuple[str, str | None]:
    pairs: list[str] = []
    search_text = query
    for m in _FILTER_RE.finditer(query):
        key = m.group(1).lower()
        val = m.group(2)
        pairs.append(f"{key}:{val}")
        search_text = search_text.replace(m.group(0), " ")
    if not pairs:
        return query.strip(), None
    return search_text.strip(), ",".join(pairs)


def _ua() -> str:
    mailto = os.environ.get("OPENALEX_MAILTO") or os.environ.get("OMNISEEK_CONTACT_EMAIL") or ""
    if mailto:
        return f"omniseek/0.1 (mailto:{mailto}; research retrieval)"
    return "omniseek/0.1 (research retrieval)"


def _http_get(url: str, timeout: int = 20) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _ua()})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"openalex.http_error: {exc}", file=sys.stderr)
        return None


def _doc_from_work(w: dict) -> dict:
    authors = []
    for a in w.get("authorships") or []:
        name = (a.get("author") or {}).get("display_name")
        if name:
            authors.append(name)
    concepts = []
    for c in (w.get("concepts") or [])[:5]:
        name = c.get("display_name")
        if name:
            concepts.append(name)
    primary_location = w.get("primary_location") or {}
    src = primary_location.get("source") or {}
    venue = src.get("display_name") if isinstance(src, dict) else None

    pub_date = w.get("publication_date")
    fetched_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    return {
        "source": "openalex",
        "source_id": (w.get("id") or "").rsplit("/", 1)[-1] or w.get("id", ""),
        "title": (w.get("title") or w.get("display_name") or "").strip() or "(untitled)",
        "url": w.get("doi") or w.get("id") or "",
        "content": _abstract(w),
        "authors": authors,
        "published_at": (pub_date + "T00:00:00Z") if pub_date else None,
        "fetched_at": fetched_at,
        "metadata": {
            "doi": w.get("doi"),
            "type": w.get("type"),
            "venue": venue,
            "cited_by_count": w.get("cited_by_count"),
            "is_oa": w.get("open_access", {}).get("is_oa"),
            "oa_url": w.get("open_access", {}).get("oa_url"),
            "concepts": concepts,
            "language": w.get("language"),
            "fwci": w.get("fwci"),
        },
    }


def _abstract(w: dict) -> str:
    # OpenAlex stores abstracts as a dict with the inverted-index format
    ab = w.get("abstract_inverted_index")
    if not isinstance(ab, dict):
        return ""
    # Reconstruct text from inverted index
    word_positions: list[tuple[int, str]] = []
    for word, positions in ab.items():
        for p in positions or []:
            word_positions.append((p, word))
    word_positions.sort()
    return " ".join(w for _, w in word_positions)


def search(query: str, limit: int = 10, type_: str | None = None) -> list[dict]:
    search_text, filter_str = _parse_filters(query)
    if type_ and "type:" not in (filter_str or ""):
        filter_str = ((filter_str + ",") if filter_str else "") + f"type:{type_}"

    params = {
        "search": search_text,
        "per-page": str(min(limit, 50)),
    }
    if filter_str:
        params["filter"] = filter_str

    url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"
    data = _http_get(url)
    if not data:
        return []
    return [_doc_from_work(w) for w in (data.get("results") or [])]


def main() -> int:
    p = argparse.ArgumentParser(description="OpenAlex scholarly works search")
    p.add_argument("query", help="Search query (supports inline key:value filters)")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--type", dest="type_", help="Work type filter: article, dissertation, book, etc.")
    args = p.parse_args()

    docs = search(args.query, limit=args.limit, type_=args.type_)
    json.dump(docs, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())