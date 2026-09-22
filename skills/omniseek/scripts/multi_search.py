#!/usr/bin/env python3
"""Fan-out search across multiple sources in one call.

Reads a query and a comma-separated list of source names, invokes each source
script as a subprocess in parallel, captures stdout, and emits a merged
JSON list. This is the "broad sweep" pattern from SKILL.md.

You typically don't call this directly — let the orchestrating agent call
each script individually so it can decide routing. But for batch jobs and
broad sweeps, this is convenient.

Examples:
    python3 multi_search.py "transformer attention" --sources arxiv,openalex,semantic_scholar --limit 5
    python3 multi_search.py "PhD application" --sources reddit,hackernews,bluesky --limit 10
    python3 multi_search.py "machine learning" --sources arxiv,openalex --parallel 4 --out results.json
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()


def _invoke_source(name: str, query: str, limit: int, extra_args: list[str]) -> tuple[str, list[dict]]:
    # Try the canonical paths in order: scripts/<name>.py,
    # scripts/walled/<name>.py, scripts/walled/<name>_search.py.
    # This lets multi_search fan out across both free and walled sources
    # without the caller caring about subdirectory layout.
    candidates = [
        SCRIPT_DIR / f"{name}.py",
        SCRIPT_DIR / "walled" / f"{name}.py",
        SCRIPT_DIR / "walled" / f"{name}_search.py",
    ]
    script = next((c for c in candidates if c.exists()), None)
    if script is None:
        print(
            f"multi_search: unknown source '{name}' (tried {', '.join(c.name for c in candidates)})",
            file=sys.stderr,
        )
        return name, []
    cmd = [sys.executable, str(script), query, "--limit", str(limit), *extra_args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        print(f"multi_search: {name} timed out", file=sys.stderr)
        return name, []
    if proc.returncode != 0:
        print(f"multi_search: {name} exited {proc.returncode}: {proc.stderr[:200]}", file=sys.stderr)
        return name, []
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        print(f"multi_search: {name} returned non-JSON: {exc}", file=sys.stderr)
        return name, []
    return name, out if isinstance(out, list) else []


def main() -> int:
    p = argparse.ArgumentParser(description="Fan out a query across multiple sources in parallel")
    p.add_argument("query", help="The query to send to every source")
    p.add_argument("--sources", required=True, help="Comma-separated source names, e.g. arxiv,openalex,semantic_scholar")
    p.add_argument("--limit", type=int, default=5, help="Per-source cap (default 5)")
    p.add_argument("--parallel", type=int, default=4, help="Max concurrent sources (default 4)")
    p.add_argument("--extra-args", default="", help="Extra args forwarded to every source, e.g. '--year 2024'")
    p.add_argument("--out", help="Write merged results to this path (also prints to stdout)")
    args = p.parse_args()

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    extra = args.extra_args.split() if args.extra_args.strip() else []

    merged: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as ex:
        futures = {ex.submit(_invoke_source, s, args.query, args.limit, extra): s for s in sources}
        for fut in concurrent.futures.as_completed(futures):
            _name, docs = fut.result()
            merged.extend(docs)

    text = json.dumps(merged, indent=2, ensure_ascii=False)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())