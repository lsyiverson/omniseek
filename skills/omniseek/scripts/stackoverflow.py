#!/usr/bin/env python3
"""Stack Overflow: programming Q&A via Stack Exchange v2.3 public API.

10000 requests/day unauthenticated, shared per-IP quota. For
implementation-style questions (pytorch, JAX, numpy, CUDA, training, data
preprocessing) Stack Overflow is the canonical answer site.

Docs: https://api.stackexchange.com/docs
Endpoint: GET /2.3/search/advanced?order=desc&sort=relevance&q=<query>&site=stackoverflow

Examples:
    python3 stackoverflow.py "pytorch dataloader" --limit 5
    python3 stackoverflow.py "cuda out of memory" --tagged python pytorch --limit 10
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ENDPOINT = "https://api.stackexchange.com/2.3"
SITE = "stackoverflow"


def _http_get(url: str, timeout: int = 20) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "omniseek-mavis/0.1 (research retrieval)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"stackoverflow.http_error: {exc}", file=sys.stderr)
        return None


def _iso(s: int | None) -> str | None:
    if not s:
        return None
    return datetime.fromtimestamp(s, timezone.utc).isoformat().replace("+00:00", "Z")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _question_doc(q: dict) -> dict:
    return {
        "source": "stackoverflow_question",
        "source_id": f"q{q.get('question_id')}" if q.get("question_id") else "",
        "title": (q.get("title") or "").strip(),
        "url": q.get("link") or "",
        "content": (q.get("body") or "")[:3000],
        "authors": [q.get("owner", {}).get("display_name")] if q.get("owner") else [],
        "published_at": _iso(q.get("creation_date")),
        "fetched_at": _now(),
        "metadata": {
            "kind": "question",
            "tags": q.get("tags") or [],
            "score": q.get("score"),
            "is_answered": q.get("is_answered"),
            "answer_count": q.get("answer_count"),
            "view_count": q.get("view_count"),
        },
    }


def _answer_doc(question: dict, a: dict) -> dict:
    qid = question.get("question_id")
    return {
        "source": "stackoverflow_answer",
        "source_id": f"q{qid}a{a.get('answer_id')}" if qid and a.get("answer_id") else "",
        "title": f"A: {question.get('title') or ''}",
        "url": a.get("link") or question.get("link") or "",
        "content": (a.get("body") or "")[:3000],
        "authors": [a.get("owner", {}).get("display_name")] if a.get("owner") else [],
        "published_at": _iso(a.get("creation_date")),
        "fetched_at": _now(),
        "metadata": {
            "kind": "answer",
            "question_id": qid,
            "is_accepted": a.get("is_accepted"),
            "score": a.get("score"),
        },
    }


def _top_answers(question_id: int, top_n: int = 3) -> list[dict]:
    """Fetch the top-voted answers for a question (best signal)."""
    params = {
        "order": "desc",
        "sort": "votes",
        "site": SITE,
        "filter": "default",
        "pagesize": str(top_n),
    }
    url = f"{ENDPOINT}/questions/{question_id}/answers?{urllib.parse.urlencode(params)}"
    data = _http_get(url)
    if not isinstance(data, dict):
        return []
    return data.get("items") or []


def search(query: str, limit: int = 10, tagged: list[str] | None = None) -> list[dict]:
    params = {
        "order": "desc",
        "sort": "relevance",
        "site": SITE,
        "pagesize": str(min(limit, 30)),
        "filter": "default",
    }
    if tagged:
        params["tagged"] = ";".join(tagged)
    url = f"{ENDPOINT}/search/advanced?{urllib.parse.urlencode(params)}&q={urllib.parse.quote(query)}"
    data = _http_get(url)
    if not isinstance(data, dict):
        return []
    questions = data.get("items") or []
    docs: list[dict] = []
    for q in questions:
        docs.append(_question_doc(q))
        qid = q.get("question_id")
        if qid:
            for a in _top_answers(qid, top_n=2):
                docs.append(_answer_doc(q, a))
    return docs


def main() -> int:
    p = argparse.ArgumentParser(description="Stack Overflow programming Q&A search")
    p.add_argument("query", help="Free-text search query")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--tagged", nargs="*", help="Restrict to one or more tags (space separated)")
    args = p.parse_args()

    docs = search(args.query, limit=args.limit, tagged=args.tagged)
    json.dump(docs, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())