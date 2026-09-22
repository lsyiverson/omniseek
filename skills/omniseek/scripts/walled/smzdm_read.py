#!/usr/bin/env python3
"""什么值得买 (smzdm.com) post detail via CDP on port 9226 — body + comments + engagement.

smzdm post pages (``https://post.smzdm.com/p/<id>/``) are gated behind a
client-side probe + Tencent captcha that triggers on any non-browser fingerprint.
A real Chrome passes the probe and renders the full page server-side. No smzdm
login is required to *read* posts, but you DO need a persistent Chrome on a
dedicated CDP port. We use **9226** (the next free port after 9225 douyin).

IMPORTANT for callers: ``web_fetch`` / plain HTTP against ``post.smzdm.com``
or ``www.smzdm.com`` will reliably hit the captcha interstitial — don't waste
a retry on it. Go straight to this script (or drive a local browser tool) the
first time you see a smzdm URL; no login step is required first, just a
running Chrome on port 9226 (``scripts/launch_browser.sh 9226``).

This complements ``smzdm.py`` (the RSS aggregator) and ``walled/xiaohongshu_read.py``
in the same walled-script pattern: launch a Chrome, the script drives it via CDP,
read-only, never touches your login cookies.

Examples:
    # Read one post
    python3 scripts/walled/smzdm_read.py "https://post.smzdm.com/p/ak8km369/"

    # Batch — one URL per line
    python3 scripts/walled/smzdm_read.py --file /tmp/smzdm_urls.txt --max-comments 30

    # Search → read pipeline
    python3 scripts/smzdm.py "显卡" --limit 3 \\
        | python3 -c "import json,sys; print('\\n'.join(d['url'] for d in json.load(sys.stdin)))" \\
        | xargs python3 scripts/walled/smzdm_read.py --max-comments 20
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

PORT = 9226
POST_URL_RE = re.compile(r"^https?://post\.smzdm\.com/p/([a-z0-9]+)/?", re.IGNORECASE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _extract_count(text: str | None) -> int | None:
    if not text:
        return None
    m = re.search(r"\d[\d,]*", text)
    if not m:
        return None
    try:
        return int(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _extract_post_id(url: str) -> str | None:
    m = POST_URL_RE.match(url.strip())
    return m.group(1) if m else None


def _looks_like_captcha(html: str) -> bool:
    """smzdm serves a Tencent captcha interstitial when the fingerprint probe fails.
    Detect it so we can return a clear error instead of an empty Document."""
    return ("TCaptcha" in html) or ("TencentCaptcha" in html) or ("captcha.show" in html)


def _parse_publish_time(html: str) -> tuple[str | None, str | None]:
    """Best-effort publish-time extraction. Priority:
      1. ``<meta property="article:published_time" content="2026-09-21T09:06:20+08:00">``
      2. ``<meta property="og:release_date" content="2026-09-21 09:06:20">``
      3. ``<meta name="pubdate" content="...">``
      4. JS-side ``"publish_time": "..."``
      5. JS-side ``"public_time": "..."``
      6. First ``YYYY-MM-DD HH:MM:SS`` literal in the body
    """
    m = re.search(
        r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']',
        html, re.IGNORECASE,
    )
    raw = m.group(1) if m else None
    if not raw:
        m = re.search(
            r'<meta[^>]+property=["\']og:release_date["\'][^>]+content=["\']([^"\']+)["\']',
            html, re.IGNORECASE,
        )
        raw = m.group(1) if m else None
    if not raw:
        m = re.search(r'<meta[^>]+name=["\']?pubdate["\']?[^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        raw = m.group(1) if m else None
    if not raw:
        m = re.search(r'"publish_time"\s*:\s*["\']([^"\']+)["\']', html)
        raw = m.group(1) if m else None
    if not raw:
        m = re.search(r'"public_time"\s*:\s*["\']([^"\']+)["\']', html)
        raw = m.group(1) if m else None
    if not raw:
        m = re.search(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?)(?:[+\-]\d{2}:?\d{2})?", html)
        raw = m.group(1) if m else None

    iso: str | None = None
    if raw:
        # Try ISO-8601 first (handles "2026-09-21T09:06:20+08:00")
        try:
            dt = datetime.fromisoformat(raw.strip().replace(" ", "T"))
            iso = dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            return iso, raw
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(raw.strip(), fmt)
                iso = dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
                break
            except ValueError:
                continue
    return iso, raw


def _extract_body(html: str) -> tuple[str, str]:
    """Return (body_text, author_name). The actual smzdm layout (verified 2026):
       <div class="m-contant">
         <article id="articleId" articleid="11_...">
           <h1 class="item-name">TITLE</h1>
           <p itemprop="description">paragraphs / images</p>
           ...
         </article>
       </div>
    Author is in either:
      • <meta property="og:author" content="GuanZ_GHz">
      • <input ... data-authername="GuanZ_GHz">     (note: typo'd "auther")
    NOTE: ``id="articleContent"`` ALSO exists but is a hidden input (``<input
    type="hidden" id="articleContent" value="">``) and selecting it returns the
    empty input. ``.article-contant`` is the typo'd class used only by the
    RELATED-articles sidebar/footer (40+ matches, none for the main article).
    The reliable selectors are therefore ``.m-contant article`` / ``#articleId`` /
    ``h1.item-name``.
    """
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 not installed; pip install beautifulsoup4")
    soup = BeautifulSoup(html, "html.parser")

    # Main body — the article element wrapped by .m-contant
    body_el = (
        soup.select_one(".m-contant article")
        or soup.select_one("article#articleId")
        or soup.select_one("#articleId")
        or soup.select_one(".m-contant")
    )
    body_text = body_el.get_text("\n", strip=True) if body_el else ""

    # Author — prefer og:author meta, then the data-authername input, then DOM
    author = None
    og = soup.select_one("meta[property='og:author']")
    if og and og.get("content"):
        author = og["content"].strip()
    if not author:
        inp = soup.select_one("[data-authername]")
        if inp and inp.get("data-authername"):
            author = inp["data-authername"].strip()
    if not author:
        for sel in (
            ".author-info .author-name",
            ".article-author .author-name",
            ".article-info .name",
            ".author_meta .author_name",
            ".feed-user a",
            ".author-name",
            ".author_meta",
        ):
            el = soup.select_one(sel)
            if el:
                author = el.get_text(strip=True)
                break
    return body_text[:8000], author or ""


def _extract_engagement(html: str) -> dict:
    """Article-level like / collect / share / comment count.

    Verified smzdm toolbar markup (2026) is wildly inconsistent across the
    buttons — only data-type / title are reliable, but the count itself is
    rendered in three different shapes:

      * 赞 (like)      : <a data-type="zan"> <span class="feed-number">5</span>
      * 收藏 (collect)  : <a data-type="fav"> <span>5</span>             ← no class!
      * 分享 (share)   : <a data-type="share"><em>0</em>
      * 评论 (comments): <a href="#comments"><em>9</em>

    We use the data-type attribute as the primary key and look for the
    count in the first numeric span / em / i inside the anchor. Falls back
    to the title attribute for buttons missing data-type.
    """
    if BeautifulSoup is None:
        return {"likes": None, "collects": None, "comments": None, "shares": None}

    soup = BeautifulSoup(html, "html.parser")
    out = {"likes": None, "collects": None, "comments": None, "shares": None}

    def _anchor_count(a) -> int | None:
        """First numeric value inside an anchor. Tolerates the three count
        shapes smzdm uses (feed-number span, plain span, em)."""
        # Most reliable first: a child with class feed-number
        for el in a.select(".feed-number, [class*='feed-number']"):
            n = _extract_count(el.get_text(strip=True))
            if n is not None:
                return n
        # Fallback: any direct child whose text is purely a number (1-6 digits)
        for el in a.find_all(["span", "em", "i"], recursive=True):
            txt = el.get_text(strip=True)
            if txt and txt.replace(",", "").isdigit() and len(txt) <= 7:
                return int(txt.replace(",", ""))
        return None

    # PRIMARY: data-type attribute
    for a in soup.select("a[data-type]"):
        dtype = (a.get("data-type") or "").strip().lower()
        n = _anchor_count(a)
        if n is None:
            continue
        if dtype == "zan" and out["likes"] is None:
            out["likes"] = n
        elif dtype == "fav" and out["collects"] is None:
            out["collects"] = n
        elif dtype in ("share", "forward") and out["shares"] is None:
            out["shares"] = n

    # SECONDARY: title attribute (for buttons that lack data-type)
    if out["likes"] is None or out["collects"] is None or out["shares"] is None:
        for a in soup.select("a[title]"):
            t = (a.get("title") or "").strip()
            n = _anchor_count(a)
            if n is None:
                continue
            if t == "赞" and out["likes"] is None:
                out["likes"] = n
            elif t == "收藏" and out["collects"] is None:
                out["collects"] = n
            elif t in ("分享", "转发") and out["shares"] is None:
                out["shares"] = n

    # Comments: anchor with href="#comments"
    for a in soup.select("a[href='#comments']"):
        n = _anchor_count(a)
        if n is not None:
            out["comments"] = n
            break
    if out["comments"] is None:
        el = soup.select_one(".commentNum, [class*='commentNum']")
        if el:
            out["comments"] = _extract_count(el.get_text(strip=True))

    return out


def _extract_comments(html: str, cap: int) -> list[dict]:
    """Each comment is ``<li class="comment-main-list-item">`` containing:
      • .comment-main-list-item-content-header  → author nick + 举报 button
      • .comment-main-list-item-content-comment → body text
      • .comment-main-list-item-content-info    → date + like count
    Sub-replies are siblings in the same flat list (smzdm doesn't nest)."""
    if BeautifulSoup is None:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for li in soup.select("li.comment-main-list-item"):
        if len(out) >= cap:
            return out

        # Author — header text is "<nick> ... 举报"
        header = li.select_one(".comment-main-list-item-content-header")
        author = ""
        if header:
            txt = header.get_text(" ", strip=True)
            m = re.search(r"^(.*?)举报", txt)
            if m and m.group(1).strip():
                # The nick is the last non-trivial token before 举报
                toks = [t for t in m.group(1).split() if t]
                author = toks[-1] if toks else ""
            else:
                for tok in txt.split():
                    if tok and tok not in ("举报",):
                        author = tok
                        break

        # Text
        txt = ""
        cmt_el = li.select_one(".comment-main-list-item-content-comment")
        if cmt_el:
            txt_el = cmt_el.select_one("[class*='comment-content-textarea'], [class*='textarea']")
            if txt_el:
                txt = txt_el.get_text(" ", strip=True)
            else:
                txt = cmt_el.get_text(" ", strip=True)

        if not txt:
            continue

        # Date + likes from .comment-main-list-item-content-info
        date_text = ""
        likes = 0
        info_el = li.select_one(".comment-main-list-item-content-info")
        if info_el:
            info_txt = info_el.get_text(" ", strip=True)
            date_text = info_txt
            lm = re.search(r"(\d+)\s*赞", info_txt)
            if lm:
                likes = int(lm.group(1))

        key = (author, txt[:80])
        if key in seen:
            continue
        seen.add(key)

        out.append({
            "author": author,
            "text": txt[:1500],
            "likes": likes,
            "date_text": date_text[:60],
        })

    return out


def _flow(page, url: str, max_comments: int) -> dict:
    page.goto(url, wait_until="domcontentloaded", timeout=25000)
    # Wait for the real body wrapper, not the hidden input id="articleContent".
    try:
        page.wait_for_selector(".m-contant article, #articleId, h1.item-name", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(800)  # let toolbar counters settle
    html = page.content()

    if _looks_like_captcha(html):
        raise RuntimeError(
            "smzdm is serving a captcha interstitial; the Chrome on port "
            f"{PORT} is not passing the fingerprint probe. Try: launch a fresh "
            "Chrome via scripts/launch_browser.sh — its fingerprint should pass."
        )

    return _parse_html(html, url, max_comments)


def _parse_html(html: str, url: str, max_comments: int) -> dict:
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 not installed")

    post_id = _extract_post_id(url) or url
    body_text, author = _extract_body(html)
    published_at, raw_time = _parse_publish_time(html)
    engagement = _extract_engagement(html)
    comments = _extract_comments(html, cap=max_comments)

    soup = BeautifulSoup(html, "html.parser")
    # h1.item-name is the canonical title — no separator stripping (titles like
    # "RTX 5080 HOF Deluxe-X" contain hyphens we must preserve).
    title_el = soup.select_one("h1.item-name, .m-contant h1, .article-title")
    title = title_el.get_text(strip=True) if title_el else ""
    if not title:
        og = soup.select_one("meta[property='og:title']")
        if og and og.get("content"):
            # og:title carries the "_显卡_什么值得买" suffix; strip the LAST "_什么值得买" suffix
            title = og["content"].strip()
            smzdm_suffix = title.rfind("_什么值得买")
            if smzdm_suffix > 0:
                title = title[:smzdm_suffix]
    title = title.strip()

    return {
        "source": "smzdm",
        "source_id": post_id,
        "title": title or "(untitled)",
        "url": url,
        "content": body_text,
        "authors": [author] if author else [],
        "published_at": published_at,
        "fetched_at": _now(),
        "metadata": {
            "kind": "smzdm_post",
            "feed_url": "https://post.smzdm.com/feed",
            "publisher": "什么值得买",
            "time_text": raw_time,
            "engagement": engagement,
            "comment_count_actual": len(comments),
            "comments": comments,
        },
    }


def read_one(url: str, max_comments: int = 30) -> dict | None:
    post_id = _extract_post_id(url)
    if not post_id:
        print(f"walled/smzdm_read: URL must be https://post.smzdm.com/p/<id>/ — got: {url}", file=sys.stderr)
        return None

    ok, msg = cdp_health(PORT)
    if not ok:
        print(f"walled/smzdm_read: {msg}", file=sys.stderr)
        return None

    try:
        return cdp_call(
            port=PORT,
            callback=lambda page: _flow(page, url, max_comments),
            timeout_ms=45000,
        )
    except Exception as exc:
        print(f"walled/smzdm_read: failed to read {url}: {exc}", file=sys.stderr)
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
        description="smzdm post detail (body + comments + engagement) via CDP on port 9226"
    )
    p.add_argument("urls", nargs="*", help="Post URLs (https://post.smzdm.com/p/<id>/)")
    p.add_argument("--file", help="File with one URL per line")
    p.add_argument("--max-comments", type=int, default=30, help="Cap comments per post (default 30)")
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