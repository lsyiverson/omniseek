#!/usr/bin/env python3
"""NGA (NGA玩家社区, bbs.nga.cn) search + thread reader via the persistent
logged-in Chrome on port 9222.

NGA is China's largest gaming / 二次元 / 数码 / 生活 forum. There is no public
API and no keyless mirror: search requires a logged-in account (guests get a
login wall on ``thread.php?key=``), most boards gate reading behind login, and
the site throttles search to a few requests per minute per account. So this is
a walled source in the same shape as ``walled/zhihu.py``: you launch a real
Chrome, log in to NGA by hand once, and this script drives that session over
CDP.

Two modes, one script (search hits are useless without the thread body):

  search   ``thread.php?key=<query>&__inchst=UTF8`` → one Document per thread
           hit (tid, title, board, author, replies, last-reply time).
  read     ``read.php?tid=<tid>&page=<n>`` → one Document per thread, with
           ``content`` = the post bodies and ``metadata.posts`` = the flat
           floor list ``[{floor, pid, author, uid, published_at, text}]``.

Prerequisites:
    ~/.omniseek/venv (playwright + beautifulsoup4) or: pip install playwright beautifulsoup4
    scripts/launch_browser.sh 9222 https://bbs.nga.cn
        # log in to NGA by hand in the window, then leave it running

Examples:
    # Keyword search (title match)
    python3 scripts/walled/nga.py "黑神话 显卡 帧数" --limit 10

    # Search inside post bodies instead of titles
    python3 scripts/walled/nga.py "4080 驱动" --in-post --limit 5

    # Scope the search to one board (fid), e.g. -7 = 网事杂谈
    python3 scripts/walled/nga.py "装修 预算" --fid -7 --limit 5

    # Read the threads a search returned (tid from the hit list)
    python3 scripts/walled/nga.py --read 44321111 --max-posts 30
    python3 scripts/walled/nga.py --read-url "https://bbs.nga.cn/read.php?tid=44321111"
    python3 scripts/walled/nga.py --read-file /tmp/nga_tids.txt --max-posts 20 --max-pages 3

    # Overseas / mirror domain
    python3 scripts/walled/nga.py "原神 攻略" --domain ngabbs.com

Selector drift: NGA ships UI changes without warning. If a run returns []
while the page obviously rendered, dump the HTML and re-measure:
    python3 scripts/walled/nga.py "关键词" --dump-html /tmp/nga.html
The parser is deliberately layered (explicit selectors → ``read.php?tid=`` /
``postcontent`` regex scan) so small markup changes degrade instead of break.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _cdp import cdp_call, cdp_health  # noqa: E402

try:
    from bs4 import BeautifulSoup  # type: ignore
except ImportError:
    BeautifulSoup = None  # type: ignore

# Port 9222 is the shared CN-forum Chrome (same one walled/zhihu.py uses).
PORT = 9222

DOMAINS = {
    "bbs.nga.cn": "https://bbs.nga.cn",
    "ngabbs.com": "https://ngabbs.com",
    "nga.178.com": "https://nga.178.com",
}
DEFAULT_DOMAIN = "bbs.nga.cn"

# NGA timestamps are Beijing time (UTC+8) with no zone suffix.
CST = timezone(timedelta(hours=8))

_TID_IN_HREF = re.compile(r"read\.php\?[^\"'\s#]*?\btid=(\d+)")
_TID_IN_ID = re.compile(r"^t_tt_(\d+)$")
_CONTENT_ID = re.compile(r"^postcontent(\d+)$")
_COUNT_WORDS = re.compile(
    r"^[\s\d]*(?:回复|查看|收藏|赞|分享|最后(?:回复|发表))\s*[\s:：]*[\d\s]*$"
)

# NGA gate/notice pages. Match on specific phrases only — the word "登录"
# alone appears in the nav of every page, so a bare /登录/ would false-positive.
_GATES: list[tuple[str, str, str]] = [
    (
        r"您需要登录|请先(?:行)?登录|登录后(?:才)?(?:能|可)|尚未登录|游客.{0,6}(?:需要|请).{0,4}登录",
        "login_required",
        "NGA served a login wall. Log in to NGA in the Chrome on port 9222 "
        "(scripts/launch_browser.sh 9222 https://bbs.nga.cn), then retry.",
    ),
    (
        r"搜索.{0,4}间隔|间隔.{0,6}(?:过短|不能少于|限制)|搜索(?:请求)?(?:太|过)"
        r"(?:快|于频繁|频繁)|搜索次数|搜索过于频繁|您今天的搜索次数|无法进行搜索"
        r"|操作(?:过于)?频繁|本操作(?:已)?受到限制",
        "search_rate_limited",
        "NGA search throttle hit (NGA allows only a few searches per minute "
        "per account). Wait, lower --limit, or retry later.",
    ),
    (
        r"阅读权限|您无权|没有权限|无权(?:访问|查看|浏览)|该版块.{0,6}(?:权限|不可)|用户组.{0,8}无法",
        "no_permission",
        "This NGA board/thread needs more account privilege than the "
        "logged-in account has (阅读权限 / 用户组限制).",
    ),
    (
        r"主题(?:已)?被删除|帖子不存在|主题不存在|该主题已(?:被)?锁定|指定的主题不存在",
        "thread_unavailable",
        "The NGA thread is deleted or locked.",
    ),
    (
        r"验证码|人机验证|滑动验证|captcha",
        "captcha",
        "NGA served a captcha — back off (per-account 风控) and retry later "
        "in the real Chrome window.",
    ),
]

_NO_RESULT = re.compile(r"没有找到|未找到|无相关|没有相关")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

def search_url(domain: str, query: str, fid: str | None = None, in_post: bool = False) -> str:
    params: dict[str, str] = {"key": query, "__inchst": "UTF8"}
    if fid:
        params["fid"] = str(fid)
    if in_post:
        params["searchpost"] = "1"
    return f"{DOMAINS[domain]}/thread.php?{urllib.parse.urlencode(params)}"


def thread_url(domain: str, tid: str, page: int | None = None) -> str:
    params: dict[str, str] = {"tid": str(tid)}
    if page and page > 1:
        params["page"] = str(page)
    return f"{DOMAINS[domain]}/read.php?{urllib.parse.urlencode(params)}"


def _extract_tid(value: str) -> str | None:
    """Accept a bare tid or a read.php?tid=... URL."""
    v = (value or "").strip()
    if v.isdigit():
        return v
    m = re.search(r"\btid=(\d+)", v) or re.search(r"/(\d{4,})(?:\D|$)", v)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------

def detect_gate(html: str) -> tuple[str | None, str]:
    """Return (gate_kind, message). gate_kind is None when the page looks usable."""
    for pattern, kind, msg in _GATES:
        if re.search(pattern, html):
            return kind, msg
    return None, ""


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------

def parse_nga_time(text: str | None) -> tuple[str | None, str | None]:
    """Find an NGA timestamp in free text; return (iso_utc, raw_text).

    NGA renders absolute times as ``2026-09-21 09:06`` / ``2026-09-21 09:06:20``
    (Beijing time). Board rows sometimes show ``09-21 09:06`` (current year) or
    a relative word (今天/昨天/前天).
    """
    if not text:
        return None, None
    text = _clean(text)

    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?", text)
    if m:
        y, mo, d, hh, mm = (int(m.group(i)) for i in range(1, 6))
        ss = int(m.group(6) or 0)
        try:
            dt = datetime(y, mo, d, hh, mm, ss, tzinfo=CST)
        except ValueError:
            return None, m.group(0)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), m.group(0)

    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if m:
        y, mo, d = (int(m.group(i)) for i in range(1, 4))
        try:
            dt = datetime(y, mo, d, tzinfo=CST)
        except ValueError:
            return None, m.group(0)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), m.group(0)

    now = datetime.now(CST)
    m = re.search(r"(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?", text)
    if m:
        mo, d, hh, mm = (int(m.group(i)) for i in range(1, 5))
        ss = int(m.group(5) or 0)
        try:
            dt = datetime(now.year, mo, d, hh, mm, ss, tzinfo=CST)
            if dt > now + timedelta(days=1):
                dt = dt.replace(year=now.year - 1)
        except ValueError:
            return None, m.group(0)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), m.group(0)

    for word, delta in (("昨天", 1), ("前天", 2)):
        if word in text:
            dt = (now - timedelta(days=delta)).replace(hour=0, minute=0, second=0, microsecond=0)
            return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), word
    if "今天" in text:
        dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), "今天"
    return None, None


def _first_int(pattern: str, text: str) -> int | None:
    m = re.search(pattern, text or "")
    if not m:
        return None
    try:
        return int(m.group(1))
    except (ValueError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Search page parsing
# ---------------------------------------------------------------------------

def _nearest_row(el, max_depth: int = 8):
    """Walk up to the row-like ancestor that holds the hit's metadata."""
    node = el
    best = None
    for _ in range(max_depth):
        node = getattr(node, "parent", None)
        if node is None or getattr(node, "name", None) in (None, "body", "html", "[document]"):
            break
        if node.name in ("tr", "li"):
            return node
        if node.name in ("div", "table", "dl", "section") and best is None:
            text = _clean(node.get_text(" ", strip=True))
            if len(text) <= 4000:
                best = node
    return best or el


def _parse_search_html(html: str, query: str, limit: int, domain: str,
                       fid: str | None = None, in_post: bool = False) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    base = DOMAINS[domain]

    anchors = list(soup.select('a[id^="t_tt_"]'))
    anchors += list(soup.select('a[href*="read.php?tid="]'))
    if not anchors:
        anchors = list(soup.find_all("a", href=_TID_IN_HREF))

    docs: list[dict] = []
    seen: set[str] = set()
    for a in anchors:
        if len(docs) >= limit:
            break
        href = a.get("href") or ""
        m = _TID_IN_HREF.search(href)
        tid = m.group(1) if m else None
        if not tid:
            m2 = _TID_IN_ID.match(_clean(a.get("id")))
            tid = m2.group(1) if m2 else None
        if not tid or tid in seen:
            continue

        title = _clean(a.get_text(" ", strip=True))
        if len(title) < 2 or _COUNT_WORDS.match(title):
            continue  # reply-count / "最后回复" anchors carry no title

        seen.add(tid)
        row = _nearest_row(a)
        row_text = _clean(row.get_text(" ", strip=True)) if row is not None else ""

        author = None
        board = None
        if row is not None:
            ua = row.select_one('a[href*="uid="]')
            if ua is not None:
                name = _clean(ua.get_text())
                if 0 < len(name) <= 40:
                    author = name
            ba = row.select_one('a[href*="thread.php?fid="]')
            if ba is not None:
                name = _clean(ba.get_text())
                if 0 < len(name) <= 40:
                    board = name

        replies = _first_int(r"(\d+)\s*(?:条)?回复", row_text)
        if replies is None:
            replies = _first_int(r"回复[：:\s]*(\d+)", row_text)
        published, raw_time = parse_nga_time(row_text)

        docs.append({
            "source": "nga",
            "source_id": tid,
            "title": title,
            "url": f"{base}/read.php?tid={tid}",
            "content": row_text[:600],
            "authors": [author] if author else [],
            "published_at": published,
            "fetched_at": _now(),
            "metadata": {
                "kind": "nga_thread_hit",
                "platform": domain,
                "tid": tid,
                "board": board,
                "fid": fid,
                "query": query[:60],
                "search_mode": "post" if in_post else "title",
                "replies": replies,
                "time_text": raw_time,
                "row_text": row_text[:300],
            },
        })
    return docs


# ---------------------------------------------------------------------------
# Thread page parsing
# ---------------------------------------------------------------------------

def _read_title(soup) -> str:
    for sel in ("h1#postsubject0", "#postsubject0", ".topic-title", ".postTitle h1",
                "#m_posts h1", "h1"):
        el = soup.select_one(sel)
        if el is not None:
            text = _clean(el.get_text(" "))
            if text:
                return text
    t = soup.find("title")
    text = _clean(t.get_text(" ")) if t is not None else ""
    for suffix in (" - NGA玩家社区", "| NGA玩家社区", " - NGA", "|NGA玩家社区"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    return _clean(text)


def _select_post_nodes(soup) -> list:
    """Return the post-content nodes, best selector first, deduped by identity."""
    candidates = list(soup.find_all(id=_CONTENT_ID))
    if not candidates:
        candidates = list(soup.select('[id^="postcontent"]'))
    if not candidates:
        candidates = list(soup.select("td.postcontent, .postcontent, [class*='postcontent']"))

    out: list = []
    seen: set[int] = set()
    for el in candidates:
        if id(el) in seen:
            continue
        seen.add(id(el))
        if _clean(el.get_text(" ")):
            out.append(el)
    return out


def _post_container(node):
    """Closest ancestor that looks like a whole post row (has an author link)."""
    cur = getattr(node, "parent", None)
    fallback = cur
    for _ in range(6):
        if cur is None or getattr(cur, "name", None) in (None, "body", "html", "[document]"):
            break
        text_len = len(_clean(cur.get_text(" ", strip=True)))
        if cur.select_one('a[href*="uid="]') is not None and text_len <= 20000:
            fallback = cur
        cls = " ".join(cur.get("class") or [])
        cid = cur.get("id") or ""
        if (re.match(r"^post1strow", cid) or "postrow" in cls or "postbody" in cls) and \
                cur.select_one('a[href*="uid="]') is not None:
            return cur
        cur = getattr(cur, "parent", None)
    return fallback or node


def _post_author(container) -> tuple[str | None, str | None]:
    if container is None:
        return None, None
    for a in container.select('a[href*="uid="]'):
        href = a.get("href") or ""
        m = re.search(r"uid=(-?\d+)", href)
        name = _clean(a.get_text())
        if not m or not name or len(name) > 40:
            continue
        if name in ("登录", "注册", "回复", "举报", "私信", "资料", "只看他", "收藏"):
            continue
        return name, m.group(1)
    return None, None


def _parse_read_html(html: str, tid: str, domain: str, page: int = 1,
                     max_posts: int = 30) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = _read_title(soup)

    board = None
    ba = soup.select_one('a[href*="thread.php?fid="]')
    if ba is not None:
        name = _clean(ba.get_text())
        if 0 < len(name) <= 40:
            board = name

    posts: list[dict] = []
    seen_text: set[str] = set()
    for node in _select_post_nodes(soup):
        if len(posts) >= max_posts:
            break
        text = re.sub(r"\n{3,}", "\n\n", node.get_text("\n", strip=True)).strip()
        if not text:
            continue

        cid = _clean(node.get("id"))
        m = _CONTENT_ID.match(cid)
        pid = m.group(1) if m else None

        # Key on the pid when we have one: two different floors can legitimately
        # carry identical text ("顶", "+1") and must not be collapsed.
        key = pid or text[:120]
        if key in seen_text:
            continue
        seen_text.add(key)

        container = _post_container(node)
        author, uid = _post_author(container)
        container_text = _clean(container.get_text(" ", strip=True)) if container is not None else ""
        published, raw_time = parse_nga_time(container_text)

        posts.append({
            "floor": len(posts) + 1,
            "pid": pid,
            "author": author,
            "uid": uid,
            "published_at": published,
            "time_text": raw_time,
            "text": text[:6000],
        })

    body = "\n\n---\n\n".join(
        f"[{p['floor']}楼 {p['author'] or '?'}] {p['text']}" for p in posts
    )
    reply_count = _first_int(r"(\d+)\s*(?:条)?回复", _clean(soup.get_text(" "))[:200000])

    return {
        "source": "nga",
        "source_id": tid,
        "title": title or f"NGA thread {tid}",
        "url": thread_url(domain, tid, page),
        "content": body[:12000],
        "authors": [posts[0]["author"]] if posts and posts[0]["author"] else [],
        "published_at": posts[0]["published_at"] if posts else None,
        "fetched_at": _now(),
        "metadata": {
            "kind": "nga_thread",
            "platform": domain,
            "tid": tid,
            "board": board,
            "page": page,
            "post_count_extracted": len(posts),
            "reply_count_text": reply_count,
            "posts": posts,
        },
    }


# ---------------------------------------------------------------------------
# Browser flows
# ---------------------------------------------------------------------------

def _settle(page) -> None:
    """Trigger lazy hydration, then let the DOM stop growing."""
    for y in (300, 900, 1800):
        try:
            page.evaluate(f"window.scrollTo(0, {y})")
            page.wait_for_timeout(900)
        except Exception:
            break


def _search_flow(page, query: str, limit: int, domain: str, fid: str | None,
                 in_post: bool, dump_html: str | None) -> list[dict]:
    page.goto(search_url(domain, query, fid=fid, in_post=in_post),
              wait_until="domcontentloaded", timeout=30000)
    try:
        page.wait_for_selector('a[id^="t_tt_"], a[href*="read.php?tid="]', timeout=12000)
    except Exception:
        pass  # either hydrated later or a gate page — the parse handles both
    _settle(page)
    html = page.content()

    if dump_html:
        Path(dump_html).write_text(html, encoding="utf-8")
        print(f"walled/nga: raw HTML written to {dump_html}", file=sys.stderr)

    gate, msg = detect_gate(html)
    if gate:
        raise RuntimeError(f"{gate}: {msg}")

    docs = _parse_search_html(html, query, limit, domain, fid=fid, in_post=in_post)
    if not docs and _NO_RESULT.search(html):
        print(f"walled/nga: NGA reports no results for {query!r}", file=sys.stderr)
    return docs


def _read_flow(page, tid: str, domain: str, max_posts: int, max_pages: int,
               dump_html: str | None) -> dict | None:
    first_doc: dict | None = None
    all_posts: list[dict] = []

    for page_no in range(1, max(1, max_pages) + 1):
        page.goto(thread_url(domain, tid, page_no),
                  wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_selector('[id^="postcontent"], .postcontent, #postsubject0', timeout=12000)
        except Exception:
            pass
        _settle(page)
        html = page.content()

        if dump_html and page_no == 1:
            Path(dump_html).write_text(html, encoding="utf-8")
            print(f"walled/nga: raw HTML written to {dump_html}", file=sys.stderr)

        gate, msg = detect_gate(html)
        if gate:
            raise RuntimeError(f"{gate}: {msg}")

        doc = _parse_read_html(html, tid, domain, page=page_no, max_posts=max_posts)
        if first_doc is None:
            first_doc = doc

        page_posts = doc["metadata"]["posts"]
        if not page_posts:
            break
        for p in page_posts:
            if len(all_posts) >= max_posts:
                break
            p["floor"] = len(all_posts) + 1
            p["page"] = page_no
            all_posts.append(p)
        if len(all_posts) >= max_posts or len(page_posts) < 10:
            break  # short page = last page
        page.wait_for_timeout(2500)  # be polite between paginated fetches — NGA throttles hard

    if first_doc is None:
        return None

    body = "\n\n---\n\n".join(
        f"[{p['floor']}楼 {p['author'] or '?'}] {p['text']}" for p in all_posts
    )
    first_doc["content"] = body[:12000]
    first_doc["metadata"]["posts"] = all_posts
    first_doc["metadata"]["post_count_extracted"] = len(all_posts)
    return first_doc


def _require_deps() -> bool:
    if BeautifulSoup is None:
        print("walled/nga: beautifulsoup4 not installed; pip install beautifulsoup4", file=sys.stderr)
        return False
    return True


def search(query: str, limit: int = 10, *, domain: str = DEFAULT_DOMAIN,
           fid: str | None = None, in_post: bool = False,
           dump_html: str | None = None) -> list[dict]:
    if not _require_deps():
        return []
    ok, msg = cdp_health(PORT)
    if not ok:
        print(f"walled/nga: {msg}", file=sys.stderr)
        return []
    try:
        return cdp_call(
            port=PORT,
            callback=lambda page: _search_flow(page, query, limit, domain, fid, in_post, dump_html),
            timeout_ms=45000,
        )
    except Exception as exc:
        print(f"walled/nga: search failed for {query!r}: {exc}", file=sys.stderr)
        return []


def read_one(tid_or_url: str, *, domain: str = DEFAULT_DOMAIN, max_posts: int = 30,
             max_pages: int = 1, dump_html: str | None = None) -> dict | None:
    tid = _extract_tid(tid_or_url)
    if not tid:
        print(f"walled/nga: cannot parse a tid out of {tid_or_url!r} "
              f"(pass a tid like 44321111 or a read.php?tid= URL)", file=sys.stderr)
        return None
    if not _require_deps():
        return None
    ok, msg = cdp_health(PORT)
    if not ok:
        print(f"walled/nga: {msg}", file=sys.stderr)
        return None
    try:
        return cdp_call(
            port=PORT,
            callback=lambda page: _read_flow(page, tid, domain, max_posts, max_pages, dump_html),
            timeout_ms=45000,
        )
    except Exception as exc:
        print(f"walled/nga: read failed for tid={tid}: {exc}", file=sys.stderr)
        return None


def main() -> int:
    p = argparse.ArgumentParser(
        description="NGA (bbs.nga.cn) search + thread reader via CDP on port 9222"
    )
    p.add_argument("query", nargs="?", help="Search query (search mode)")
    p.add_argument("--limit", type=int, default=10, help="Max search hits (default 10, cap 50)")
    p.add_argument("--fid", help="Restrict search to one board, e.g. -7 (网事杂谈)")
    p.add_argument("--in-post", action="store_true",
                   help="Full-text search inside post bodies instead of titles")
    p.add_argument("--domain", choices=sorted(DOMAINS), default=DEFAULT_DOMAIN,
                   help=f"NGA domain (default {DEFAULT_DOMAIN})")
    p.add_argument("--read", metavar="TID", help="Read mode: thread id")
    p.add_argument("--read-url", help="Read mode: read.php?tid=... URL")
    p.add_argument("--read-file", help="Read mode: file with one tid/URL per line")
    p.add_argument("--max-posts", type=int, default=30, help="Cap posts per thread (default 30)")
    p.add_argument("--max-pages", type=int, default=1, help="Thread pages to read (default 1, cap 10)")
    p.add_argument("--dump-html", help="Write the raw page HTML here (selector debugging)")
    args = p.parse_args()

    args.limit = max(1, min(args.limit, 50))
    args.max_posts = max(1, min(args.max_posts, 200))
    args.max_pages = max(1, min(args.max_pages, 10))

    targets: list[str] = []
    if args.read:
        targets.append(args.read)
    if args.read_url:
        targets.append(args.read_url)
    if args.read_file:
        path = Path(args.read_file)
        if not path.exists():
            print(f"walled/nga: no such file: {path}", file=sys.stderr)
            return 1
        targets.extend(
            line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )

    if targets:
        if args.query:
            print("walled/nga: pass either a search query or --read/--read-url/--read-file, not both",
                  file=sys.stderr)
            return 1
        docs = []
        for target in targets:
            doc = read_one(
                target,
                domain=args.domain,
                max_posts=args.max_posts,
                max_pages=args.max_pages,
                dump_html=args.dump_html,
            )
            if doc is not None:
                docs.append(doc)
        json.dump(docs, sys.stdout, indent=2, ensure_ascii=False)
        print()
        return 0

    if not args.query:
        p.print_help(sys.stderr)
        return 1

    docs = search(
        args.query,
        limit=args.limit,
        domain=args.domain,
        fid=args.fid,
        in_post=args.in_post,
        dump_html=args.dump_html,
    )
    json.dump(docs, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
