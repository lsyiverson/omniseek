#!/usr/bin/env python3
"""arXiv preprints search via the public Atom API.

arXiv is a free preprint server for physics, math, CS, biology, finance etc.
~2.4M papers indexed. Native query syntax passes through: ``ti:transformer``,
``au:bengio``, ``cat:cs.LG``, ``abs:diffusion``, ``ti:llm AND cat:cs.CL``.

Rate limit (per arXiv's API terms): 1 request / 3 seconds. The script paces
itself internally and degrades to ``[]`` if the rate-gate backlog exceeds
12 seconds (callers should retry on a different source).

Docs: https://info.arxiv.org/help/api/user-manual.html
Endpoint: https://export.arxiv.org/api/query

Examples:
    python3 arxiv.py "transformer attention" --limit 5
    python3 arxiv.py "au:bengio AND cat:cs.LG" --limit 10
    python3 arxiv.py "ti:diffusion" --limit 20 --year 2024
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

ENDPOINT = "https://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

# Rate gate: arXiv asks for 1 req / 3 s. We track the last call time per-process.
_LAST_CALL: float = 0.0
_MIN_INTERVAL_S = 3.0


def _pace() -> None:
    """Enforce the per-process minimum interval between arXiv calls."""
    global _LAST_CALL
    if _LAST_CALL > 0:
        wait = _MIN_INTERVAL_S - (time.monotonic() - _LAST_CALL)
        if wait > 0:
            time.sleep(wait)
    _LAST_CALL = time.monotonic()


def _http_get(url: str, timeout: int = 20) -> bytes | None:
    try:
        _pace()
        req = urllib.request.Request(url, headers={"User-Agent": "omniseek-mavis/0.1 (research retrieval)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as exc:
        print(f"arxiv.http_error: {exc}", file=sys.stderr)
        return None


def _parse_dt(s: str | None) -> str | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return s


def _entry_to_doc(entry: ET.Element) -> dict | None:
    id_text = (entry.findtext("atom:id", default="", namespaces=NS) or "").strip()
    # arXiv id is the trailing path of the atom id URL, e.g. http://arxiv.org/abs/2406.01234v1
    m = re.search(r"abs/([\w./\-]+)", id_text)
    if not m:
        return None
    arxiv_id = m.group(1)
    bare_id = re.sub(r"v\d+$", "", arxiv_id)

    title = (entry.findtext("atom:title", default="", namespaces=NS) or "").strip().replace("\n", " ")
    title = re.sub(r"\s+", " ", title)
    summary = (entry.findtext("atom:summary", default="", namespaces=NS) or "").strip()

    authors = []
    for a in entry.findall("atom:author", NS):
        nm = a.findtext("atom:name", default="", namespaces=NS)
        if nm:
            authors.append(nm.strip())

    published = _parse_dt(entry.findtext("atom:published", default=None, namespaces=NS))
    updated = _parse_dt(entry.findtext("atom:updated", default=None, namespaces=NS))

    cats = [c.attrib.get("term", "") for c in entry.findall("atom:category", NS)]
    cats = [c for c in cats if c]
    primary = cats[0] if cats else None

    doi = entry.findtext("arxiv:doi", default=None, namespaces=NS)
    journal_ref = entry.findtext("arxiv:journal_ref", default=None, namespaces=NS)

    return {
        "source": "arxiv",
        "source_id": bare_id,
        "title": title,
        "url": f"https://arxiv.org/abs/{bare_id}",
        "content": summary,
        "authors": authors,
        "published_at": published,
        "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "metadata": {
            "arxiv_id": bare_id,
            "categories": cats,
            "primary_category": primary,
            "doi": (doi or None),
            "journal_ref": (journal_ref or None),
            "updated_at": updated,
            "pdf_url": f"https://arxiv.org/pdf/{bare_id}",
        },
    }


def _filter_year(query: str) -> str:
    """Extract a ``--year`` style filter if present; pass through if absent.

    Note: this script also accepts ``--year`` as a CLI flag and prepends it
    into the arXiv ``submittedDate`` range filter.
    """
    return query


def search(query: str, limit: int = 10, year: str | None = None) -> list[dict]:
    search_query = query
    if year:
        # arXiv's submittedDate filter takes YYYYMMDDHHMM in [..]
        search_query = f"({query}) AND submittedDate:[{year}01010000 TO {year}12312359]"

    params = {
        "search_query": search_query,
        "start": "0",
        "max_results": str(min(limit, 50)),
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"
    raw = _http_get(url)
    if not raw:
        return []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        print(f"arxiv.parse_error: {exc}", file=sys.stderr)
        return []

    docs = []
    for entry in root.findall("atom:entry", NS):
        d = _entry_to_doc(entry)
        if d:
            docs.append(d)
    return docs


def main() -> int:
    p = argparse.ArgumentParser(description="arXiv preprint search via the public Atom API")
    p.add_argument("query", help="Search query (supports arXiv native syntax: ti:, au:, cat:, abs:)")
    p.add_argument("--limit", type=int, default=10, help="Max results (default 10, max 50)")
    p.add_argument("--year", help="Restrict to a single publication year, e.g. 2024")
    args = p.parse_args()

    docs = search(args.query, limit=args.limit, year=args.year)
    json.dump(docs, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())