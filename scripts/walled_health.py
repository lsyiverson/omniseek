#!/usr/bin/env python3
"""Walled-tier health probe — is each Chrome up and logged in?

Probes the four standard CDP ports and prints one line per port. Use this
when a walled source returns empty and you want to know whether the
browser crashed, was never launched, or is logged out.

Examples:
    python3 scripts/walled_health.py
    python3 scripts/walled_health.py --ports 9222,9223
    python3 scripts/walled_health.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running this script directly (without installing the skill as a package)
sys.path.insert(0, str(Path(__file__).parent))
from _cdp import DEFAULT_PORTS, cdp_health  # noqa: E402


PORT_LABELS = {
    9222: "shared (zhihu, yipinsanfendi, etc.)",
    9223: "xiaohongshu (international)",
    9224: "xiaohongshu (mainland)",
    9225: "douyin",
}


def main() -> int:
    p = argparse.ArgumentParser(description="Probe walled-source Chrome CDP endpoints")
    p.add_argument("--ports", help=f"Comma-separated ports (default: {','.join(str(p) for p in DEFAULT_PORTS.values())})")
    p.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    args = p.parse_args()

    if args.ports:
        ports = [int(x) for x in args.ports.split(",") if x.strip()]
    else:
        ports = list(DEFAULT_PORTS.values())

    results = {}
    for port in ports:
        ok, msg = cdp_health(port)
        results[port] = {"ok": ok, "message": msg}

    if args.json:
        json.dump(results, sys.stdout, indent=2)
        print()
    else:
        any_dead = False
        for port, info in results.items():
            label = PORT_LABELS.get(port, "custom")
            mark = "OK " if info["ok"] else "DEAD"
            if not info["ok"]:
                any_dead = True
            print(f"  [{mark}] port {port:5}  ({label})")
            print(f"         {info['message']}")
        print()
        if any_dead:
            print("Fix: scripts/launch_browser.sh <port>  (then log in by hand in the window)")
            return 1
        print("All probed ports are alive.")
    return 0


if __name__ == "__main__":
    sys.exit(main())