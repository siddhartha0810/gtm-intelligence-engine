"""
competitor_churn_watch.py
==========================
Churn detection pointed at COMPETITORS: watch a rival vendor's public
/customers page through the Wayback Machine and report which customer logos
were quietly REMOVED between two archived snapshots. A company that churned
from Gainsight/Pendo/Totango is the hottest displacement prospect there is —
it has budget, category need, and an open vacancy where a competitor used to
be. (Built for the QuadSci account: churn prediction applied to prospecting.)

Honesty guards — the two failure modes this explicitly avoids:
  * Page redesigns masquerading as mass churn. Pendo moved its customer wall
    to client-side rendering in 2025; a naive old-vs-live diff reports ~117
    "churned" logos that are actually just a redesign. So: name-counts are
    profiled across ALL snapshots, and only STRUCTURALLY COMPARABLE pairs
    (newer count >= 60% of older count) are ever diffed.
  * Removal != churn. A logo can vanish for a rebrand, an acquisition, or a
    legal request. Output is therefore typed competitor_displacement at its
    existing 0.55 confidence — a timing hint that needs a second signal type
    to matter (the buying-window cluster rule), never a qualified prospect
    by itself. Every hit cites BOTH archived snapshots so a rep can eyeball
    the before/after pages.

Free, keyless (web.archive.org CDX + snapshot fetches), rate-limited.

Usage:
    .venv/bin/python competitor_churn_watch.py                # all competitor pages
    .venv/bin/python competitor_churn_watch.py --page pendo.io/customers/
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.request

_UA = {"User-Agent": "Mozilla/5.0 (compatible; gtm-intent-research/1.0)"}
_TIMEOUT = 60
_PAUSE = 2.0          # polite pacing between archive.org requests
_MIN_NAMES = 25       # a snapshot with fewer extracted names isn't a logo wall
_COMPARABLE = 0.6     # newer count must be >= 60% of older count to diff

# Competitor customer/case-study pages for the QuadSci ICP — the six
# competitors QuadSci itself names (legacy: Gainsight/ChurnZero/Clari;
# AI-native: Hook/Reef/Magnify), plus adjacent analytics vendors whose
# walls have usable archive depth. Coverage reality (probed 2026-07):
# only mature server-rendered walls (Pendo, Totango) yield diffable
# history today — the AI-natives have no archived customer pages yet and
# Gainsight/ChurnZero render client-side. The watch still registers them
# all: it accrues its own snapshot history from the day it's turned on;
# the public archive only looks backward for incumbents.
PAGES = [
    "gainsight.com/customers/",
    "churnzero.com/customers/",
    "clari.com/customers/",
    "usehook.com/customers",
    "reef.ai/customers",
    "magnify.io/customers",
    # adjacent analytics vendors with usable archive depth
    "pendo.io/customers/",
    "totango.com/customers",
]

_JUNK = re.compile(r"logo|icon|arrow|image|badge|avatar|photo|screenshot|customer story|"
                   r"placeholder|banner|hero|thumbnail|^customer$|story bg|^testimonial", re.I)


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return r.read().decode("utf-8", errors="ignore")


def _names(html: str, vendor_word: str) -> set[str]:
    """Customer names from img alt text — the convention every logo wall uses."""
    alts = re.findall(r"<img[^>]+alt=[\"']([^\"']{2,40})[\"']", html)
    out = set()
    for a in alts:
        a = re.sub(r"\s*(logo|company logo)\s*$", "", a, flags=re.I).strip(" _-")
        if a and not _JUNK.search(a) and vendor_word.lower() not in a.lower() and len(a) < 35:
            out.add(a)
    return out


def _snapshots(page: str) -> list[str]:
    q = (f"http://web.archive.org/cdx/search/cdx?url={page}&output=json"
         f"&fl=timestamp,statuscode&filter=statuscode:200&collapse=timestamp:6")
    rows = json.loads(_get(q))
    return [r[0] for r in rows[1:]]


def watch_page(page: str) -> dict | None:
    """Profile snapshots, pick the newest structurally comparable pair at
    least ~9 months apart, return the removal diff. None if no honest pair
    exists (e.g. the page went client-side-rendered too long ago)."""
    vendor_word = page.split(".")[0].split("/")[-1]
    try:
        snaps = _snapshots(page)
    except Exception as e:
        print(f"  [{page}] CDX failed: {e}")
        return None
    if len(snaps) < 2:
        return None

    # Sample up to 8 snapshots spread across the archive, newest last
    step = max(1, len(snaps) // 8)
    sampled = snaps[::step][-8:]
    profiles = []
    for ts in sampled:
        try:
            html = _get(f"http://web.archive.org/web/{ts}/https://{page}")
            names = _names(html, vendor_word)
            profiles.append((ts, names))
            print(f"  [{page}] {ts[:8]}: {len(names)} names")
        except Exception as e:
            print(f"  [{page}] {ts[:8]}: fetch failed ({e})")
        time.sleep(_PAUSE)

    usable = [(ts, n) for ts, n in profiles if len(n) >= _MIN_NAMES]
    if len(usable) < 2:
        print(f"  [{page}] no two structurally usable snapshots — skipping (honest miss)")
        return None

    older_ts, older = usable[0], None
    # newest comparable pair: last usable vs the earliest usable that's
    # comparable in size and at least ~9 months older
    new_ts, new_names = usable[-1]
    pair = None
    for old_ts, old_names in usable[:-1]:
        months_apart = (int(new_ts[:6]) - int(old_ts[:6]))
        if months_apart >= 9 and len(new_names) >= _COMPARABLE * len(old_names):
            pair = (old_ts, old_names)
    if not pair:
        print(f"  [{page}] snapshots exist but no comparable pair ≥9 months apart — skipping")
        return None

    old_ts, old_names = pair
    removed = sorted(old_names - new_names)
    return {
        "page": page,
        "old_ts": old_ts, "new_ts": new_ts,
        "old_count": len(old_names), "new_count": len(new_names),
        "removed": removed,
        "old_url": f"http://web.archive.org/web/{old_ts}/https://{page}",
        "new_url": f"http://web.archive.org/web/{new_ts}/https://{page}",
    }


def main() -> None:
    pages = PAGES
    if "--page" in sys.argv:
        pages = [sys.argv[sys.argv.index("--page") + 1]]
    reports = []
    for page in pages:
        print(f"▶ {page}")
        rep = watch_page(page)
        if rep:
            reports.append(rep)
            print(f"  ✓ {len(rep['removed'])} logos removed between "
                  f"{rep['old_ts'][:8]} ({rep['old_count']} names) and "
                  f"{rep['new_ts'][:8]} ({rep['new_count']} names)")
    print()
    for rep in reports:
        print(f"=== {rep['page']} — removed {rep['old_ts'][:8]} → {rep['new_ts'][:8]} ===")
        print(f"  before: {rep['old_url']}")
        print(f"  after:  {rep['new_url']}")
        for name in rep["removed"]:
            print(f"  - {name}")


if __name__ == "__main__":
    main()
