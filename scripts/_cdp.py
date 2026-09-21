"""Shared CDP (Chrome DevTools Protocol) helper for walled-garden adapters.

Connect to a Chrome running with ``--remote-debugging-port=<N>`` (see
``scripts/launch_browser.sh``), open a fresh tab, run a callback on the
page, close the tab. The remote Chrome keeps its cookies / login state
on disk; this script never sees your password.

Trust model — match upstream omniseek:
  - You launch the Chrome (or use ``launch_browser.sh``).
  - You log in to the platform in that Chrome, by hand, once.
  - We connect via CDP over loopback only (127.0.0.1).
  - Cookies live in your Chrome profile (~/.omniseek/chrome-<port>).
  - This script closes only the tab it opened — the browser stays up.

Each script invocation is a separate process, so each gets its own
``sync_playwright()`` session. They all connect to the same remote
Chrome. No shared Python state between scripts.

Usage from a walled adapter:

    from . import _cdp
    def search(query, limit=10):
        return _cdp.cdp_call(
            port=9222,
            callback=lambda page: _do_search(page, query, limit),
            initial_url=f"https://www.zhihu.com/search?q={query}&type=content",
        )
"""
from __future__ import annotations

import logging
import os
import pathlib
import sys
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Per upstream conventions:
#   9222 = shared Chrome (zhihu, yipinsanfendi, most CN forums)
#   9223 = xiaohongshu (international) — strictly serial, account-rate-sensitive
#   9224 = xiaohongshu (mainland) — second independent login
#   9225 = douyin — fully isolated
DEFAULT_PORTS = {
    "shared": 9222,
    "xiaohongshu": 9223,
    "xiaohongshu_cn": 9224,
    "douyin": 9225,
    "smzdm": 9226,
}


def _try_import_playwright():
    """Lazily import playwright so the rest of the skill loads even without it.

    Returns the sync_api module or None. Wall scripts call this at the top
    of ``main()`` and exit with a clear message if it's missing.

    Search order:
      1. Already importable on the current interpreter (e.g. user invoked
         with the venv python that has playwright installed)
      2. The opt-in venv at ``~/.omniseek/venv`` (the documented install
         location; matches the venv this skill's installer creates)
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
        return sync_playwright
    except ImportError:
        pass

    # Fall back: try the documented venv at ~/.omniseek/venv
    venv_py = pathlib.Path.home() / ".omniseek" / "venv" / "bin" / "python"
    if venv_py.exists():
        try:
            import subprocess
            # Test if playwright is importable inside the venv
            subprocess.check_output(
                [str(venv_py), "-c", "from playwright.sync_api import sync_playwright"],
                stderr=subprocess.DEVNULL,
            )
            # Yes — re-exec ourselves inside the venv interpreter so the rest of
            # the script imports resolve there too. The exit happens transparently
            # to the caller; they see only the final script's output.
            os.execv(str(venv_py), [str(venv_py), *sys.argv])
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            pass  # venv exists but doesn't have playwright; fall through to error message

    return None


def cdp_health(port: int) -> tuple[bool, str]:
    """Probe whether a Chrome is listening at the given CDP port.

    Returns ``(ok, message)``. ``ok=True`` means a browser connected;
    ``message`` includes cookie count when the browser has at least one
    context (a logged-in browser typically has dozens of cookies).
    """
    sync_playwright = _try_import_playwright()
    if sync_playwright is None:
        return False, "playwright not installed; run: pip install playwright && playwright install chromium"

    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            try:
                contexts = browser.contexts
                if not contexts:
                    return True, f"port {port}: browser up, no context (login needed)"
                cookies = contexts[0].cookies()
                # Tab count helps confirm the browser is the user's persistent one, not a zombie
                page_count = sum(len(c.pages) for c in contexts)
                return True, f"port {port}: {len(cookies)} cookies, {page_count} open tabs"
            finally:
                # Do NOT call browser.close(); this is a remote browser, shared by every caller.
                pass
    except Exception as exc:
        msg = str(exc)
        if "ECONNREFUSED" in msg or "connect" in msg.lower():
            return False, f"port {port}: no browser (refused); run scripts/launch_browser.sh {port}"
        return False, f"port {port}: {exc}"


def cdp_call(
    port: int,
    callback: Callable[[Any], Any],
    initial_url: str | None = None,
    *,
    timeout_ms: int = 30000,
    wait_selector: str | None = None,
    wait_load_state: str = "domcontentloaded",
) -> Any:
    """Connect to Chrome at ``port``, open a new tab, run ``callback(page)``, close the tab.

    Args:
        port: CDP port (one of ``DEFAULT_PORTS``).
        callback: A function taking a playwright Page and returning anything.
            Its return value is forwarded to the caller.
        initial_url: If set, navigate the new tab to this URL before invoking callback.
        timeout_ms: Page navigation timeout.
        wait_selector: If set, wait for this selector to appear before invoking callback.
        wait_load_state: Playwright load state to wait for after navigation.

    Returns:
        Whatever ``callback`` returns.

    Raises:
        RuntimeError: If playwright is not installed or the browser is unreachable.
            The error message tells the user how to fix it.
    """
    sync_playwright = _try_import_playwright()
    if sync_playwright is None:
        raise RuntimeError(
            "walled source needs playwright. Install with:\n"
            "  pip install playwright\n"
            "  playwright install chromium\n"
            f"  scripts/launch_browser.sh {port}"
        )

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        except Exception as exc:
            raise RuntimeError(
                f"cannot connect to CDP port {port}: {exc}\n"
                f"  fix: scripts/launch_browser.sh {port}  (then log in by hand in the window)"
            ) from exc

        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()
        page.set_default_timeout(timeout_ms)

        try:
            if initial_url:
                page.goto(initial_url, wait_until=wait_load_state, timeout=timeout_ms)
            if wait_selector:
                page.wait_for_selector(wait_selector, timeout=timeout_ms)
            return callback(page)
        finally:
            try:
                page.close()
            except Exception:
                pass
            # Do NOT close the browser. The user owns it.