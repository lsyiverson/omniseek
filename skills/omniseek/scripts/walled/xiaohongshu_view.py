#!/usr/bin/env python3
"""Xiaohongshu (小红书) image downloader — SEE the note's own photos.

xiaohongshu_read.py extracts each note's carousel/cover image URLs into
``metadata.images``, but those URLs live behind an image CDN
(xhscdn.com / rednotecdn / sns-webpic-qc) that 403s a plain request without
a matching ``Referer``. This script downloads them properly so you can look
at the actual bytes (via the Read tool, or hand the paths to your own vision)
instead of only reading the note's text.

No CDP / logged-in browser is required to download the images themselves —
the image CDN is public once you send the right headers. ``--note-url`` is
the one exception: it re-invokes ``xiaohongshu_read`` first to get the image
list, which DOES need the 9223 Chrome (same as ``xiaohongshu_read.py``).

Two ways to call it:
  1. Pass image URLs directly (e.g. copy/pasted from a note's
     ``metadata.images``, or piped from ``xiaohongshu_read.py``'s JSON).
  2. Pass a note URL with ``--note-url`` — this re-invokes
     ``xiaohongshu_read.read_one`` (needs the 9223 Chrome) to fetch the note
     first, then downloads whatever ``metadata.images`` it finds.

Examples:
    # Download image URLs you already have
    python3 scripts/walled/xiaohongshu_view.py \\
        "https://sns-webpic-qc.xhscdn.com/.../1.jpg" \\
        "https://sns-webpic-qc.xhscdn.com/.../2.jpg" \\
        --out-dir /tmp/xhs_imgs

    # Read a note, then download all of its images in one step
    python3 scripts/walled/xiaohongshu_view.py \\
        --note-url "https://www.xiaohongshu.com/search_result/...?xsec_token=..." \\
        --out-dir /tmp/xhs_imgs

    # From a file of URLs (one per line)
    python3 scripts/walled/xiaohongshu_view.py --file /tmp/xhs_image_urls.txt

Output: a JSON array of ``{"url", "path", "bytes", "error"}`` — one entry per
URL, in input order. ``path`` is set only when the download succeeded; feed
those paths to a file-reading tool to actually SEE the images.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _UA,
    "Referer": "https://www.xiaohongshu.com/",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}
_MAX_BYTES = 25 * 1024 * 1024  # refuse to buffer a pathological >25MB "image"


def _guess_ext(url: str, content_type: str | None) -> str:
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"):
        if url.split("?", 1)[0].lower().endswith(ext):
            return ext
    if content_type:
        ct = content_type.lower()
        if "webp" in ct:
            return ".webp"
        if "png" in ct:
            return ".png"
        if "avif" in ct:
            return ".avif"
        if "gif" in ct:
            return ".gif"
    return ".jpg"


def _download_one(url: str, out_dir: Path, idx: int) -> dict:
    if not url.startswith("http"):
        return {"url": url, "error": "not an http(s) URL"}
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read(_MAX_BYTES + 1)
            content_type = resp.headers.get("Content-Type")
        if len(data) > _MAX_BYTES:
            return {"url": url, "error": f"refused: response exceeds {_MAX_BYTES}B cap"}
        if len(data) < 200:
            return {"url": url, "error": f"suspiciously small response ({len(data)}B) — likely an error page"}

        ext = _guess_ext(url, content_type)
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
        out_path = out_dir / f"xhs_{idx:02d}_{digest}{ext}"
        out_path.write_bytes(data)
        return {"url": url, "path": str(out_path), "bytes": len(data)}
    except urllib.error.HTTPError as exc:
        return {"url": url, "error": f"HTTP {exc.code}"}
    except Exception as exc:  # noqa: BLE001
        return {"url": url, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}


def download_many(urls: list[str], out_dir: Path, max_images: int = 18) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for i, url in enumerate(urls[:max_images], start=1):
        results.append(_download_one(url.strip(), out_dir, i))
    return results


def _images_from_note(note_url: str, max_comments: int, max_images: int) -> list[str]:
    """Drive xiaohongshu_read (needs the 9223 Chrome) to get metadata.images."""
    from xiaohongshu_read import read_one  # local import: same walled/ package

    doc = read_one(note_url, max_comments=max_comments, max_images=max_images)
    if doc is None:
        print("walled/xiaohongshu_view: note read failed (see xiaohongshu_read stderr above)",
              file=sys.stderr)
        return []
    images = (doc.get("metadata") or {}).get("images") or []
    if not images:
        print("walled/xiaohongshu_view: note read OK but no images extracted "
              "(pure-text note, or the carousel markup drifted)", file=sys.stderr)
    return images


def main() -> int:
    p = argparse.ArgumentParser(
        description="Download xiaohongshu note images (with the Referer the CDN requires) for in-band viewing"
    )
    p.add_argument("urls", nargs="*", help="Image URLs (e.g. from metadata.images)")
    p.add_argument("--file", help="File with one image URL per line")
    p.add_argument("--note-url", help="A note URL (with xsec_token) — read it first via CDP, then download its images")
    p.add_argument("--out-dir", default=None,
                   help="Directory to write images to (default: a fresh temp dir, printed to stderr)")
    p.add_argument("--max-images", type=int, default=18, help="Cap images downloaded (default 18)")
    p.add_argument("--max-comments", type=int, default=0,
                   help="Only used with --note-url: comments to harvest while reading the note (default 0, skip)")
    args = p.parse_args()

    urls: list[str] = list(args.urls)
    if args.file:
        with open(args.file) as f:
            urls.extend(line.strip() for line in f if line.strip() and not line.startswith("#"))
    if args.note_url:
        urls.extend(_images_from_note(args.note_url, args.max_comments, args.max_images))

    if not urls:
        print("No image URLs given. Pass them positionally, via --file, or derive them with --note-url.",
              file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir) if args.out_dir else Path(tempfile.mkdtemp(prefix="xhs_view_"))
    print(f"walled/xiaohongshu_view: writing to {out_dir}", file=sys.stderr)

    results = download_many(urls, out_dir, max_images=args.max_images)
    json.dump(results, sys.stdout, indent=2, ensure_ascii=False)
    print()
    ok = sum(1 for r in results if r.get("path"))
    print(f"walled/xiaohongshu_view: {ok}/{len(results)} image(s) downloaded", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
