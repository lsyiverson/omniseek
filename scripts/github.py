#!/usr/bin/env python3
"""GitHub: code search + issues/PRs + discussions + repo activity.

Uses GitHub's REST + GraphQL APIs. With a ``GITHUB_TOKEN`` env var (or
``~/.omniseek/credentials/github.json`` with ``{"token": "..."}``) you get the
authenticated rate limit (5000/h); without, anonymous (60/h).

Routing rules in the query:
  - ``org:NAME`` or ``user:NAME`` alone → that owner's NEWEST repos (activity mode)
  - ``tree:owner/repo`` (optionally ``tree:owner/repo@branch``) → repo file tree
  - anything else → code search + issues/PR + discussions, merged + deduped

GitHub native qualifiers (``language:``, ``is:``, ``label:``, ``state:``,
``path:``, etc.) pass through to code/issues searches.

Examples:
    python3 github.py "transformer attention language:python" --limit 10
    python3 github.py "org:huggingface" --limit 20
    python3 github.py "tree:openai/gpt-2" --limit 100
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

REST = "https://api.github.com"
GRAPHQL = "https://api.github.com/graphql"

_OWNER_ONLY_RE = re.compile(r"^\s*(org|user):([A-Za-z0-9][A-Za-z0-9-]*)\s*$", re.IGNORECASE)
_TREE_RE = re.compile(r"^\s*tree:([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)(?:@([\w./-]+))?\s*$", re.IGNORECASE)


def _load_token() -> str:
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if tok:
        return tok
    creds = os.path.expanduser("~/.omniseek/credentials/github.json")
    if os.path.exists(creds):
        try:
            with open(creds) as f:
                data = json.load(f)
                tok = (data.get("token") or "").strip()
                if tok:
                    return tok
        except Exception:
            pass
    return ""


def _headers() -> dict:
    h = {
        "User-Agent": "omniseek-mavis/0.1",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    tok = _load_token()
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _http_get(url: str, timeout: int = 20) -> dict | list | None:
    try:
        req = urllib.request.Request(url, headers=_headers())
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            if not body:
                return None
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        print(f"github.http_error: {exc.code} {exc.reason}: {body[:300]}", file=sys.stderr)
        return None
    except Exception as exc:
        print(f"github.http_error: {exc}", file=sys.stderr)
        return None


def _http_post(url: str, payload: dict, timeout: int = 20) -> dict | list | None:
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={**_headers(), "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        print(f"github.http_error: {exc.code} {exc.reason}: {body[:300]}", file=sys.stderr)
        return None
    except Exception as exc:
        print(f"github.http_error: {exc}", file=sys.stderr)
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


def _doc_from_repo(r: dict) -> dict:
    return {
        "source": "github_repo",
        "source_id": str(r.get("id")),
        "title": (r.get("full_name") or r.get("name") or ""),
        "url": r.get("html_url") or "",
        "content": (r.get("description") or "").strip(),
        "authors": [r.get("owner", {}).get("login")] if r.get("owner") else [],
        "published_at": _iso(r.get("created_at")),
        "fetched_at": _now(),
        "metadata": {
            "kind": "repo",
            "full_name": r.get("full_name"),
            "stars": r.get("stargazers_count"),
            "forks": r.get("forks_count"),
            "language": r.get("language"),
            "topics": r.get("topics") or [],
            "license": ((r.get("license") or {}).get("spdx_id") if isinstance(r.get("license"), dict) else None),
            "default_branch": r.get("default_branch"),
            "last_pushed_at": _iso(r.get("pushed_at")),
            "archived": r.get("archived"),
        },
    }


def _doc_from_issue(issue: dict) -> dict:
    return {
        "source": "github_issue",
        "source_id": f"#{issue.get('number')}" if issue.get("number") else str(issue.get("id")),
        "title": (issue.get("title") or "").strip(),
        "url": issue.get("html_url") or "",
        "content": (issue.get("body") or "")[:3000],
        "authors": [issue.get("user", {}).get("login")] if issue.get("user") else [],
        "published_at": _iso(issue.get("created_at")),
        "fetched_at": _now(),
        "metadata": {
            "kind": "issue",
            "is_pr": "pull_request" in issue,
            "state": issue.get("state"),
            "labels": [l.get("name") for l in (issue.get("labels") or []) if isinstance(l, dict)],
            "comments": issue.get("comments"),
            "repo_full_name": (issue.get("repository") or {}).get("full_name") if isinstance(issue.get("repository"), dict) else None,
        },
    }


def _doc_from_code(r: dict) -> dict:
    repo = r.get("repository") or {}
    return {
        "source": "github_code",
        "source_id": r.get("sha") or r.get("html_url"),
        "title": f"{r.get('path') or ''} — {repo.get('full_name') or ''}",
        "url": r.get("html_url") or "",
        "content": "",
        "authors": [r.get("owner")],
        "published_at": None,
        "fetched_at": _now(),
        "metadata": {
            "kind": "code",
            "path": r.get("path"),
            "repo_full_name": repo.get("full_name"),
            "language": r.get("language"),
        },
    }


def _newest_repos(owner: str, kind: str, limit: int) -> list[dict]:
    data = _http_get(f"{REST}/users/{owner}/repos?sort=created&direction=desc&per_page={min(limit, 50)}")
    if data is None:
        return []
    return [_doc_from_repo(r) for r in data if isinstance(r, dict)]


def _search_code(q: str, limit: int) -> list[dict]:
    data = _http_get(f"{REST}/search/code?q={urllib.parse.quote(q)}&per_page={min(limit, 30)}")
    if not isinstance(data, dict):
        return []
    return [_doc_from_code(r) for r in (data.get("items") or [])]


def _search_issues(q: str, limit: int) -> list[dict]:
    # Force the issues scope; the default /search/issues also returns PRs, which we keep
    data = _http_get(f"{REST}/search/issues?q={urllib.parse.quote(q)}&per_page={min(limit, 30)}")
    if not isinstance(data, dict):
        return []
    return [_doc_from_issue(r) for r in (data.get("items") or [])]


def _repo_tree(owner: str, repo: str, branch: str | None) -> list[dict]:
    """Resolve a repo's tree via the Git Trees API; returns a single 'tree' Document."""
    # Find the default branch if not given
    if not branch:
        info = _http_get(f"{REST}/repos/{owner}/{repo}")
        if not isinstance(info, dict):
            return []
        branch = info.get("default_branch") or "main"
    data = _http_get(f"{REST}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1")
    if not isinstance(data, dict):
        return []
    tree = data.get("tree") or []
    summary = {
        "source": "github_tree",
        "source_id": f"{owner}/{repo}@{branch}",
        "title": f"{owner}/{repo} ({branch}) — {len(tree)} entries",
        "url": f"https://github.com/{owner}/{repo}",
        "content": "",
        "authors": [owner],
        "published_at": None,
        "fetched_at": _now(),
        "metadata": {
            "kind": "tree",
            "owner": owner,
            "repo": repo,
            "branch": branch,
            "truncated": data.get("truncated", False),
            "entry_count": len(tree),
            "entries": [
                {
                    "path": e.get("path"),
                    "type": e.get("type"),
                    "size": e.get("size"),
                    "sha": e.get("sha"),
                }
                for e in tree[:600]  # bound the payload
            ],
        },
    }
    return [summary]


def search(query: str, limit: int = 10) -> list[dict]:
    """Top-level search entry point."""
    m_owner = _OWNER_ONLY_RE.match(query)
    if m_owner:
        return _newest_repos(m_owner.group(2), m_owner.group(1).lower(), limit)

    m_tree = _TREE_RE.match(query)
    if m_tree:
        return _repo_tree(m_tree.group(1), m_tree.group(2), m_tree.group(3))

    # Round-robin merge code + issues
    per_kind = max(1, limit // 2)
    code_docs = _search_code(query, per_kind)
    issue_docs = _search_issues(query, per_kind)
    merged: list[dict] = []
    seen: set[str] = set()
    for d in code_docs + issue_docs:
        if d["source_id"] not in seen:
            merged.append(d)
            seen.add(d["source_id"])
    return merged[:limit]


def main() -> int:
    p = argparse.ArgumentParser(description="GitHub code/issue/discussion/repo search")
    p.add_argument("query", help="Search query (GitHub native qualifiers pass through; org:/user: alone = newest repos; tree:owner/repo = file tree)")
    p.add_argument("--limit", type=int, default=10)
    args = p.parse_args()

    docs = search(args.query, limit=args.limit)
    json.dump(docs, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())