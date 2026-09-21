#!/usr/bin/env python3
"""Xiaohongshu (小红书) note detail reader via the persistent logged-in Chrome.

Drives the SAME Chrome on port 9223 that xiaohongshu_search uses — the note-detail
URL must already carry an ``xsec_token`` (which is exactly what the search grid
returns, so the two scripts compose: search → read).

For each note URL the script:
  • loads the detail page in the existing tab
  • waits for ``#detail-desc`` to render (the main note body)
  • reads title, body text, author, full publish time, like / collect / comment /
    share counts from ``#interaction-info``
  • scrolls the real (largest scrollable) comment container to lazy-load the
    first page of comments, then harvests every ``[class*="comment-item"]`` /
    ``[class*="reply-item"]`` in the DOM (sub-replies are picked up via the same
    selector pattern). The cap is ``--max-comments`` per note (default 30).

The output is one Document per note. The body lives in ``content`` (so it shows
up in merged search results), and the comment thread is parked under
``metadata.comments`` as ``[{author, text, likes}]`` — each entry is a single
flat comment; sub-replies are also flat entries (no nesting) so downstream
tools can join them without recursive walking.

Examples:
    # Read a single note (paste URL from xiaohongshu_search output)
    python3 scripts/walled/xiaohongshu_read.py \\
        "https://www.xiaohongshu.com/search_result/69dcf5aa000000001a02a106?xsec_token=..."

    # Batch — one URL per line, max 10 comments per note
    python3 scripts/walled/xiaohongshu_read.py --file /tmp/xhs_urls.txt --max-comments 10

    # Adjust depth: more comments per note, or a hard timeout
    python3 scripts/walled/xiaohongshu_read.py URL --max-comments 50 --timeout-ms 45000

Note on guest-readable URLs (verified late 2025 / 2026): only URLs that already
carry an ``xsec_token`` render the real note body. A bare ``/explore/<id>`` will
return an empty shell to a non-owner; this script reports the missing token in
stderr instead of returning a useless empty Document.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _cdp import cdp_call, cdp_health  # noqa: E402

try:
    from bs4 import BeautifulSoup  # type: ignore
except ImportError:
    BeautifulSoup = None  # type: ignore

PORT = 9223

# Selectors measured against the live site (late 2025 / 2026), cross-referenced
# against upstream omniseek's walled/xiaohongshu_source.py.
_TITLE_SEL = "#detail-title, .note-content .title"
_BODY_SEL = "#detail-desc, .note-content .desc"
_AUTHOR_SEL = ".author .name, .user-info .username, .note-content .author .name"
_TIME_SEL = ".date, .publish-time, .note-content .date, .bottom-container .date"
_INTERACTION_SEL = "#interaction-info, .interaction-info, .interaction-container"
_ENGAGEMENT_NUM_RE = re.compile(r"\d[\d,]*")
_COMMENT_CONTAINER_SELECTORS = [
    ".comments-el",
    ".comments-container",
    '[class*="comment-list"]',
    '[class*="comments-list"]',
    '[class*="comments"]',
    '[class*="comment-scroller"]',
    '[class*="scroller"]',
]
_COMMENT_NODE_SELECTORS = (
    '[class*="comment-item"]',
    '[class*="reply-item"]',
    '[class*="parent-comment"]',
)
_COMMENT_AUTHOR_SEL = "a.name, .name, .author, .comment-user"
_COMMENT_TEXT_SEL = ".note-text, .content, [class*='comment-text'], [class*='reply-text']"
_COMMENT_LIKE_SEL = ".like-count, [class*='like-count'], .interaction-info .count"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _check_xsec_token(url: str) -> bool:
    """A tokened share link is the only way guests can read a note body. Bare
    ``/explore/<id>`` URLs render an empty shell."""
    return "xsec_token=" in url


def _extract_count(text: str | None) -> int | None:
    if not text:
        return None
    m = _ENGAGEMENT_NUM_RE.search(text)
    if not m:
        return None
    try:
        return int(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _parse_publish_time(time_text: str | None) -> str | None:
    """Convert XHS detail-page time strings (e.g. '2026-09-21', '09-21', '昨天 14:23',
    '刚刚', '3 小时前') into ISO-8601 UTC. Returns None if unparseable.

    Year-less strings (MM-DD / X 小时前 / 刚刚 / 昨天) are coerced to the current
    year, on the assumption that the script is run shortly after fetch. We do
    NOT guess year-rollover across New Year — false positives there are worse
    than missing precision."""
    if not time_text:
        return None
    t = time_text.strip()
    now = datetime.now(timezone.utc)

    # Full date with year
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{2}))?", t)
    if m:
        y, mo, d, hh, mm = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4), m.group(5)
        try:
            dt = datetime(int(y), mo, d, int(hh) if hh else 0, int(mm) if mm else 0, tzinfo=timezone.utc)
            return dt.isoformat().replace("+00:00", "Z")
        except ValueError:
            return None

    # MM-DD (year assumed current)
    m = re.match(r"^(\d{1,2})-(\d{1,2})$", t)
    if m:
        try:
            dt = datetime(now.year, int(m.group(1)), int(m.group(2)), tzinfo=timezone.utc)
            return dt.isoformat().replace("+00:00", "Z")
        except ValueError:
            return None

    # X 小时前 / X 分钟前 / X 天前 — assume recent
    m = re.match(r"^(\d+)\s*(秒|分钟|小时|天)前", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit == "秒":
            delta_seconds = n
        elif unit == "分钟":
            delta_seconds = n * 60
        elif unit == "小时":
            delta_seconds = n * 3600
        else:  # 天
            delta_seconds = n * 86400
        ts = now.timestamp() - delta_seconds
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")

    if t.startswith("刚刚"):
        return now.isoformat().replace("+00:00", "Z")

    # 昨天 HH:MM — assume yesterday same time
    m = re.match(r"^昨天\s*(\d{1,2}):(\d{2})$", t)
    if m:
        try:
            dt = now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
            from datetime import timedelta
            dt = dt - timedelta(days=1)
            return dt.isoformat().replace("+00:00", "Z")
        except ValueError:
            return None

    return None


def _largest_scrollable(page) -> str | None:
    """Return a JS selector for the largest scrollable comment container.
    We pick the one whose scrollHeight is largest — that's the real feed."""
    return page.evaluate(
        """() => {
            const sels = %s;
            let best = null, bestH = 0;
            for (const sel of sels) {
                const el = document.querySelector(sel);
                if (!el) continue;
                const h = el.scrollHeight || 0;
                if (h > bestH) { bestH = h; best = sel; }
            }
            return best;
        }""" % json.dumps(_COMMENT_CONTAINER_SELECTORS)
    )


def _scroll_to_load(page, max_rounds: int = 6) -> int:
    """Scroll the comment container down N times to trigger lazy hydration.
    Returns the final count of comment nodes in the DOM."""
    selector = _largest_scrollable(page)
    if not selector:
        # No scroll container found; fall back to window scroll
        for _ in range(max_rounds):
            page.evaluate("window.scrollBy(0, window.innerHeight)")
            page.wait_for_timeout(500)
    else:
        for _ in range(max_rounds):
            page.evaluate(
                f"""(sel) => {{
                    const el = document.querySelector(sel);
                    if (el) el.scrollTop = el.scrollHeight;
                }}""",
                selector,
            )
            page.wait_for_timeout(500)
    return page.evaluate(
        """() => {
            let n = 0;
            for (const sel of %s) {
                n += document.querySelectorAll(sel).length;
            }
            return n;
        }""" % json.dumps(_COMMENT_NODE_SELECTORS)
    )


def _harvest_comments(html: str, cap: int) -> list[dict]:
    """Parse the rendered comment thread from the page HTML. We dedupe by
    (author, text) so a comment that scrolls into view twice doesn't double-count.
    Sub-replies are picked up by the same selector pattern but we DON'T try to
    reconstruct the parent→reply tree; consumers can group by time + author."""
    if BeautifulSoup is None:
        print("walled/xiaohongshu_read: beautifulsoup4 not installed", file=sys.stderr)
        return []

    soup = BeautifulSoup(html, "html.parser")
    seen: set[tuple[str, str]] = set()
    comments: list[dict] = []

    for sel in _COMMENT_NODE_SELECTORS:
        for node in soup.select(sel):
            if len(comments) >= cap:
                return comments

            # Author: prefer a.name, fall back to any .name/.author
            author_el = node.select_one(_COMMENT_AUTHOR_SEL)
            author = author_el.get_text(strip=True) if author_el else ""

            # Text: .note-text is the dominant pattern; fall back to .content
            text_el = node.select_one(_COMMENT_TEXT_SEL)
            text = text_el.get_text(" ", strip=True) if text_el else ""
            if not text:
                continue

            like_el = node.select_one(_COMMENT_LIKE_SEL)
            likes = _extract_count(like_el.get_text(strip=True) if like_el else None) or 0

            key = (author, text[:80])
            if key in seen:
                continue
            seen.add(key)

            comments.append({
                "author": author,
                "text": text[:1500],
                "likes": likes,
            })

    return comments


def _flow(page, url: str, max_comments: int) -> dict:
    """Navigate to one note URL, harvest body + comments. Raises if no body."""
    # Use the existing tab — the user already navigated to xiaohongshu.com
    page.goto(url, wait_until="domcontentloaded", timeout=20000)

    # Body must render — that's the gate
    try:
        page.wait_for_selector(_BODY_SEL, timeout=15000)
    except Exception:
        # Could be the missing-xsec-token case (empty shell). Let the caller see
        # the actual page state — they can re-fetch from a token-bearing URL.
        raise RuntimeError(
            "note body did not render — likely missing xsec_token or rate-limited; "
            "URL must come from xiaohongshu_search (which carries the token)"
        )

    page.wait_for_timeout(800)  # let counters / sidebar hydrate

    # Scroll comments area (best effort — if no comments, just no-op)
    try:
        _scroll_to_load(page, max_rounds=4)
    except Exception as exc:
        print(f"walled/xiaohongshu_read: scroll failed ({exc}); comments may be empty", file=sys.stderr)

    html = page.content()
    return _parse_html(html, url, max_comments)


def _parse_html(html: str, url: str, max_comments: int) -> dict:
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 not installed")
    soup = BeautifulSoup(html, "html.parser")

    title_el = soup.select_one(_TITLE_SEL)
    title = title_el.get_text(strip=True) if title_el else ""

    body_el = soup.select_one(_BODY_SEL)
    body_text = body_el.get_text("\n", strip=True) if body_el else ""

    author_el = soup.select_one(_AUTHOR_SEL)
    author = author_el.get_text(strip=True) if author_el else None

    time_el = soup.select_one(_TIME_SEL)
    time_text = time_el.get_text(strip=True) if time_el else None
    published_at = _parse_publish_time(time_text)

    # Engagement counts: #interaction-info holds "like_count text + collect_count + comment_count + share_count"
    engagement = {"likes": None, "collects": None, "comments": None, "shares": None}
    inter_el = soup.select_one(_INTERACTION_SEL)
    if inter_el:
        # Look at span children with class containing count
        for span in inter_el.select("span"):
            cls = " ".join(span.get("class") or [])
            count = _extract_count(span.get_text(strip=True))
            if count is None:
                continue
            if "like" in cls.lower() or "like" in (span.get("data-type") or "").lower():
                engagement["likes"] = count
            elif "collect" in cls.lower() or "favor" in cls.lower():
                engagement["collects"] = count
            elif "comment" in cls.lower() or "chat" in cls.lower():
                engagement["comments"] = count
            elif "share" in cls.lower() or "forward" in cls.lower():
                engagement["shares"] = count

    comments = _harvest_comments(html, cap=max_comments)

    # Source ID: same logic as xiaohongshu_search — the 24-hex from the path
    parsed = urllib.parse.urlparse(url)
    m = re.search(r"/(explore|search_result)/([0-9a-f]{16,32})", parsed.path)
    note_id = m.group(2) if m else None
    if not note_id:
        # Fall back to whichever hash-like token is in the path
        m2 = re.search(r"/(share|note)/([0-9a-f]{16,32})", parsed.path)
        if m2:
            note_id = m2.group(2)

    return {
        "source": "xiaohongshu",
        "source_id": note_id or url,
        "title": title or "(untitled)",
        "url": url,
        "content": body_text[:8000],  # full body; downstream tools truncate
        "authors": [author] if author else [],
        "published_at": published_at,
        "fetched_at": _now(),
        "metadata": {
            "kind": "xiaohongshu_note",
            "platform": "xiaohongshu.com",
            "time_text": time_text,
            "engagement": engagement,
            "comment_count_actual": len(comments),
            "comments": comments,
        },
    }


def read_one(url: str, max_comments: int = 30) -> dict | None:
    if not _check_xsec_token(url):
        print(
            f"walled/xiaohongshu_read: URL missing xsec_token (bare /explore/<id> renders empty): {url}",
            file=sys.stderr,
        )
        return None

    ok, msg = cdp_health(PORT)
    if not ok:
        print(f"walled/xiaohongshu_read: {msg}", file=sys.stderr)
        return None

    try:
        return cdp_call(
            port=PORT,
            callback=lambda page: _flow(page, url, max_comments),
            timeout_ms=45000,
        )
    except Exception as exc:
        print(f"walled/xiaohongshu_read: failed to read {url}: {exc}", file=sys.stderr)
        return None


def read_many(urls: list[str], max_comments: int = 30) -> list[dict]:
    out: list[dict] = []
    for url in urls:
        url = url.strip()
        if not url or url.startswith("#"):
            continue
        doc = read_one(url, max_comments=max_comments)
        if doc is not None:
            out.append(doc)
    return out


def main() -> int:
    p = argparse.ArgumentParser(
        description="Read xiaohongshu note details (body + comments) via CDP on port 9223"
    )
    p.add_argument("urls", nargs="*", help="Note URLs (must carry xsec_token)")
    p.add_argument("--file", help="File with one URL per line")
    p.add_argument("--max-comments", type=int, default=30, help="Cap comments per note (default 30)")
    p.add_argument("--timeout-ms", type=int, default=45000, help="Per-note CDP timeout (default 45s)")
    args = p.parse_args()

    urls: list[str] = list(args.urls)
    if args.file:
        with open(args.file) as f:
            urls.extend(line.strip() for line in f if line.strip() and not line.startswith("#"))

    if not urls:
        print("No URLs given. Pass them as positional args or via --file.", file=sys.stderr)
        return 1

    docs = read_many(urls, max_comments=args.max_comments)
    json.dump(docs, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())