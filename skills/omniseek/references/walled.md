# Walled sources — bring your own browser

Some of the highest-signal corners of the web sit behind a **login**:
Xiaohongshu, Zhihu, Douyin, WeChat, and other platforms that no search
engine indexes and no public API exposes. This skill can reach them, but
only on **your** behalf, through **your** logged-in browser.

This guide explains the trust model, the setup, and the boundary you must
respect.

> **Walled sources are OFF by default.** They are the advanced,
> bring-your-own-account tier. You opt in deliberately (by running a walled
> script), and you accept operator responsibility for using each platform
> within its Terms of Service in your jurisdiction. See "Boundary" below.

---

## The trust model — read this first

This skill **never sees your password**. It does not store your
credentials, and it does not log in for you.

```
   your account                  a Chrome you run                  this skill
  ─────────────       log in     ───────────────        CDP      ────────────
  zhihu.com  ────────────────▶   --remote-debug-port ◀────────   walled/zhihu.py
  (your session)   (you, by hand)  --port=9222          connect   (the script
                                  (session on disk)              you ran)
```

1. **You** launch a real Chrome on your own machine with remote debugging.
2. **You** log into the platform in that browser, once, by hand.
3. This skill connects via the **Chrome DevTools Protocol (CDP)** over
   loopback (127.0.0.1) and drives the browser to read what your logged-in
   session can already see.

Your session lives in the browser's own profile directory on your disk
(`~/.omniseek/chrome-<port>`). Nothing credential-bearing ever enters the
skill's process. If you close the browser or log out, the skill simply
can't reach that source until you log back in. This is the same posture as
a person opening a tab: we reach only what you, the account holder, are
already entitled to see.

---

## Boundary — what you are responsible for

Driving a logged-in browser is **not** the same as public scraping. The
sites you read have Terms of Service that govern automated access to your
own account. You, the operator, accept responsibility for:

- **Rate-limiting**: keep `--limit` small (5-20 results per call). Don't
  hammer the platform. If a script returns 429 / captcha / "操作频繁", back
  off for hours.
- **Serial, not parallel**: never open multiple tabs/pages on a walled
  source at once, and never fan out multiple `walled/*.py` calls in a
  single parallel batch. Drive one page at a time — search, read, wait a
  beat, then move to the next — to minimize the odds of tripping the
  platform's risk-control.
- **Account-specific rules**: each platform may forbid automation even of
  your own data. Read the platform's ToS in your jurisdiction before
  running a walled source against it.
- **Sharing**: don't redistribute the content the walled sources fetch.
  These sources are for your own retrieval, not for republishing.
- **Local-only**: the scripts connect to `127.0.0.1` only. If you bind the
  CDP port to a public interface, the trust model collapses — anyone who
  can reach the port can drive your logged-in browser. Don't.

If you're unsure whether a specific use is OK, **don't run the script.**

---

## Setup

### 1. Install the optional dependency

The walled tier needs the browser-automation engine. This is an **opt-in**
install — without it, every free-tier script still works, and every walled
script fails with a clear error.

**Step 1a — always required** (the Python package):

```bash
pip install playwright beautifulsoup4
```

**Step 1b — required ONLY if you have no local Chrome** (the browser
binary):

```bash
# SKIP this if you already have Google Chrome / Chromium / Chrome for
# Testing installed. The walled scripts use connect_over_cdp (remote
# attach), not launch() (local spawn), so playwright only needs the
# Python package — it never spawns its own browser when you launch
# Chrome via scripts/launch_browser.sh.

# Run this ONLY if you have no local Chrome / Chromium at all:
playwright install chromium
```

If you don't need the walled tier, skip step 1a too. The other 22 scripts
in this skill work without it.

The script auto-detects your situation: if a walled source complains
about missing dependencies, its error message checks for local Chrome and
tells you exactly which step to run next.

### 2. Know which port a source uses

| Source(s) | Port | Browser profile | Why isolated |
|-----------|------|-----------------|--------------|
| `walled/zhihu.py`, `walled/nga.py` (and future CN forums: yipinsanfendi, douban_groups, …) | **9222** | `~/.omniseek/chrome-9222` | one login you reuse across these sources |
| `walled/xiaohongshu_search.py` + `walled/xiaohongshu_read.py` | **9223** | `~/.omniseek/chrome-9223` | account-rate-sensitive, isolated from the shared login |
| (future) xiaohongshu mainland | **9224** | `~/.omniseek/chrome-9224` | second independent login if you hold one |
| (future) douyin | **9225** | `~/.omniseek/chrome-douyin` | account-rate-sensitive, fully isolated |
| `walled/smzdm_read.py` | **9226** | `~/.omniseek/chrome-9226` | NO smzdm login required — but a real Chrome is required to pass smzdm's fingerprint probe (else Tencent captcha) |

Multiple walled sources can share one Chrome (port 9222 is the "shared"
Chrome). The platform-specific ports are for platforms whose accounts need
to be kept separate.

### 3. Launch a Chrome on that port

The helper script detects Chrome / Chromium on macOS and Linux and
launches it with the right flags:

```bash
# Shared Chrome for zhihu + NGA (+ future CN forums)
scripts/launch_browser.sh 9222 https://bbs.nga.cn

# Dedicated Chrome for xiaohongshu, pre-opened to the login page
scripts/launch_browser.sh 9223 ~/.omniseek/chrome-9223 https://www.xiaohongshu.com
```

Flag rationale (the script picks these for you):

- `--remote-debugging-port=<N>` — enables CDP on the local port.
- `--remote-allow-origins=*` — required on Chrome 111+; without it, the
  CDP WebSocket upgrade is rejected and walled sources silently return
  empty.
- `--user-data-dir=<PROFILE>` — persists cookies / localStorage so your
  login survives restarts.
- `--disable-blink-features=AutomationControlled` — hides the
  `navigator.webdriver=true` automation tell so the site sees an ordinary
  Chrome. **Do not** add `--enable-automation`; it sets the opposite flag.
- `--disable-features=PrivacySandboxAdsAPIs` — suppresses the Privacy
  Sandbox prompt that can steal focus on launch.

### 4. Log in by hand, once

In the window that opens, log into the platform (QR scan, password,
whatever challenge). Leave the browser **running**. Because the profile is
persistent, you only do this again when the platform expires your session
(typically rare).

> **Exception — smzdm (port 9226): no login needed.** smzdm's gate is a
> client-side fingerprint/JS probe + Tencent captcha, not an auth wall. A
> plain `curl`/`web_fetch` request gets served the captcha interstitial;
> a real Chrome passes the probe and renders the page straight away —
> with or without a logged-in session. So for `walled/smzdm_read.py` you
> can skip this step entirely: just `scripts/launch_browser.sh 9226` and
> go straight to step 5. If you ever see `web_fetch` fail on a
> `post.smzdm.com` URL, don't keep retrying `web_fetch` — that domain
> always needs the real-browser path.

You can press `Ctrl-C` in the terminal that ran `launch_browser.sh` — the
browser keeps running. (The `exec` in the script replaces the shell, so
Ctrl-C in the terminal sends SIGINT to the browser; on most setups the
browser catches it and quits. If you'd rather detach, run with `nohup` or
in a separate Terminal.app window.)

### 5. Use it

```bash
# Make sure Chrome is up and logged in
python3 scripts/walled_health.py

# Search zhihu (port 9222)
python3 scripts/walled/zhihu.py "PhD 申请 流程" --limit 5

# Search NGA (port 9222) — needs a logged-in NGA account
python3 scripts/walled/nga.py "黑神话 帧数 优化" --limit 5
python3 scripts/walled/nga.py "4080 驱动" --in-post --limit 5      # full-text
python3 scripts/walled/nga.py "装修 预算" --fid -7 --limit 5       # one board

# Read a thread the search returned (tid) — body + per-floor posts
python3 scripts/walled/nga.py --read 44321111 --max-posts 20 --max-pages 2
# Or batch a hit list: search → tids → read
python3 scripts/walled/nga.py "黑神话 帧数" --limit 5 \
  | python3 -c "import json,sys; [print(d['source_id']) for d in json.load(sys.stdin)]" \
  > /tmp/nga_tids.txt
python3 scripts/walled/nga.py --read-file /tmp/nga_tids.txt --max-posts 15

# Search xiaohongshu (port 9223) — returns URLs WITH xsec_token baked in
python3 scripts/walled/xiaohongshu_search.py "字节跳动 面经" --limit 10

# Read one note body + comments (URL must come from xiaohongshu_search above)
URL=$(python3 scripts/walled/xiaohongshu_search.py "字节跳动 面经" --limit 1 \
      | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['url'])")
python3 scripts/walled/xiaohongshu_read.py "$URL" --max-comments 30

# Or batch from a file (one URL per line)
python3 scripts/walled/xiaohongshu_read.py --file /tmp/xhs_urls.txt --max-comments 50

# SEE the note's own photos: xiaohongshu_read extracts CDN image URLs into
# metadata.images. Download them (needs the right Referer header, NOT the
# CDP browser — this step is a plain HTTP fetch):
python3 scripts/walled/xiaohongshu_view.py --note-url "$URL" --out-dir /tmp/xhs_imgs
# or, if you already have the URL list (e.g. from a saved xiaohongshu_read.py run):
python3 -c "import json;d=json.load(open('/tmp/note.json'));print('\n'.join(d[0]['metadata']['images']))" \
  | python3 scripts/walled/xiaohongshu_view.py --file /dev/stdin --out-dir /tmp/xhs_imgs
# then read the downloaded files at /tmp/xhs_imgs/*.jpg with a file-viewing tool

# Merge a walled source with a free source
python3 scripts/arxiv.py "speculative decoding" --limit 5 > /tmp/papers.json
python3 scripts/walled/zhihu.py "speculative decoding 综述" --limit 5 > /tmp/zh.json
python3 scripts/normalize_doc.py /tmp/papers.json /tmp/zh.json \
    --query "speculative decoding" --sort
```

---

## Troubleshooting

```bash
python3 scripts/walled_health.py
```

Probes all four ports and prints one line per port:

```
  [OK ] port 9222  (shared (zhihu, yipinsanfendi, etc.))
         port 9222: 87 cookies, 3 open tabs
  [DEAD] port 9223  (xiaohongshu (international))
         port 9223: no browser (refused); run scripts/launch_browser.sh 9223
```

| Symptom | Cause | Fix |
|---|---|---|
| `[DEAD] port 9222` line | Chrome not launched | `scripts/launch_browser.sh 9222` |
| `connected to port 9222, no context (login needed)` | Chrome up, no cookies — likely a fresh profile | Open the window and log in |
| Wall script returns `[]` silently | Cookie expired, or site returned a login wall | Open Chrome, refresh zhihu.com, log in if redirected |
| `walled/nga: login_required: …` | NGA search + most boards require a login; the shared Chrome isn't logged into NGA | Open the 9222 window, log into bbs.nga.cn by hand, retry |
| `walled/nga: search_rate_limited: …` | NGA throttles search per account (a few per minute) | Wait, lower `--limit`, and don't loop the search |
| `walled/nga` returns `[]` but the page rendered | NGA markup drifted | Re-run with `--dump-html /tmp/nga.html` and re-measure the selectors in `walled/nga.py` |
| Wall script returns `[]` + captcha / 风控 | You hammered the site | Wait several hours; lower `--limit` |
| `RuntimeError: walled source needs playwright` | Playwright Python package missing | `pip install playwright` — and follow the auto-detected hint in the error (skip `playwright install chromium` if you already have Chrome locally) |
| `RuntimeError: cannot connect to CDP port N` | Chrome not on that port | `scripts/launch_browser.sh N` |

---

## Port hygiene

- **One Chrome per port.** Two accounts on one Chrome = cookies for both,
  on the same browser fingerprint. The platform sees one identity and
  may rate-limit both accounts together.
- **Don't reuse a Chrome across machines.** CDP is loopback-only, so the
  browser must be on the same machine as the scripts.
- **Don't bind the port to the LAN.** `--remote-debugging-port` already
  binds `127.0.0.1` on every supported OS — don't override that with
  `--remote-debugging-address`. If you need to drive a remote browser,
  use SSH port forwarding: `ssh -L 9222:127.0.0.1:9222 remote-host`.

---

## What this layer is NOT

- **Not a password manager.** The skill never sees or stores credentials.
  It connects to a browser you logged into. If you log out, every walled
  source becomes inert.
- **Not a stealth scraper.** We use `--disable-blink-features=AutomationControlled`
  to hide one tell, but we don't defeat Cloudflare / Akamai / fingerprint
  detection. If a platform blocks the request, that's a signal to stop,
  not a problem to engineer around.
- **Not a wall bypass.** The walled tier assumes you have a legitimate
  account and access to the content already. It does not help with
  credential stuffing, account farming, or bypassing rate limits.
- **Not 14 sources out of the box.** This skill ships four walled
  platforms / six scripts (`zhihu`, `nga`, `xiaohongshu_search` +
  `xiaohongshu_read` + `xiaohongshu_view`, `smzdm_read`). The upstream omniseek ships
  14 (zhihu, yipinsanfendi, xiaohongshu, xiaohongshu_cn, douyin,
  discord_communities, youtube, wechat, feishu_jobs, bytedance_seed,
  douban_groups, zhihu_users, …). Each is ~80-800 lines of CSS-selector
  brittleness. Add the ones you actually use; don't blindly port the lot.

---

## Adding a new walled source

The pattern is the same as the free-tier sources, with three differences:

1. Use `_cdp.cdp_call(port=N, callback=lambda page: ..., initial_url=...)`
   instead of `urllib.request.urlopen()`.
2. The script must fail loudly (stderr note) when playwright is missing
   or the browser isn't running — don't try to install or launch silently.
3. Respect the per-platform port convention from the table above. Don't
   reuse a port already used by a different platform.

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _cdp import cdp_call, cdp_health

PORT = 9222  # pick the right port for the platform

def search(query: str, limit: int = 10) -> list[dict]:
    ok, msg = cdp_health(PORT)
    if not ok:
        print(f"my_walled_source: {msg}", file=sys.stderr)
        return []
    return cdp_call(
        port=PORT,
        callback=lambda page: _flow(page, query, limit),
        initial_url=f"https://example.com/search?q={query}",
    )

def _flow(page, query, limit):
    page.wait_for_selector(".result-card", timeout=15000)
    html = page.content()
    return _parse_html(html, query, limit)
```

After adding the script, register it in `scripts/catalog.py` under
`"walled"` and add a row to the table above.
