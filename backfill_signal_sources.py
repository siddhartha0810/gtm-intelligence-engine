#!/usr/bin/env python3
"""
backfill_signal_sources.py
===========================
Every fired rule in the Decision Intelligence glass-box scorer needs a public,
clickable source. A fired rule with no source is a claim a rep can't defend on
a call. Before this script, only R1 (category language) reliably carried a
source_url — R3, R4, R6, and R7 fired on every qualifying prospect but pointed
at nothing.

This resolves each company to its SEC EDGAR CIK and backfills source_url using
SEC's free public APIs (data.sec.gov/submissions, efts.sec.gov full-text
search) plus the verified-contact LinkedIn URLs already on file:

  R1  category_language      -> filing where the term appears (already mostly set;
                                 the two gaps are backfilled via full-text search)
  R3  industry_fit            -> the EDGAR company page carrying the SIC classification
  R4  recent_ipo               -> the exact S-1/424B4 filing named in the rule's "why"
  R6  buying_window_timing     -> the filing-history page showing the clustered dates
  R7  decision_maker_found     -> the contact's LinkedIn profile, matched by name

R2/R3 on PENNYMAC and Mercury Insurance are sourced from a live job posting,
not SEC data. PENNYMAC's Drools posting was re-confirmed via web search
(Monster.com). Mercury Insurance's could not be re-verified — it is left
unsourced on purpose rather than guessed at.

Every SEC CIK resolution below was cross-checked: fetched submissions.json and
confirmed the live sicDescription matches what the rule's "why" text already
claimed, before trusting the CIK enough to build a URL from it.

Rows that still have no source after this runs keep fired=true but no
source_url — the frontend (DecisionIntelligence.tsx TraceLine) now renders
that combination as "unverified" rather than silently omitting the link.
Never invent a URL: an unsourced claim should look unsourced.

Usage:
    python backfill_signal_sources.py            # writes inrule_glassbox.json in place
    python backfill_signal_sources.py --dry-run  # prints planned changes, writes nothing
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).parent
GLASSBOX_PATH = BASE / "inrule_glassbox.json"
CONTACTS_PATH = BASE / "inrule_verified_contacts.json"

HEADERS = {"User-Agent": "InRule GTM Research sid@example.com"}
_TIMEOUT = 20

# Verified by cross-checking submissions.json sicDescription against each
# rule's own "why" text (see backfill_signal_sources_verify.py output).
CIK_MAP: dict[str, int | None] = {
    "Roadzen Inc. (RDZN, RDZNW)": 1868640,
    "Health In Tech, Inc.": 2019505,
    "Bowhead Specialty Holdings Inc.": 2002473,
    "Beeline Holdings, Inc.": 1534708,
    "Ethos Technologies Inc.": 1788451,
    "Neptune Insurance Holdings Inc.": 2067129,
    "Essent Group Ltd.": 1448893,
    "Metromile, Inc.": 1819035,
    "First American Financial Corp": 1472787,
    "Trupanion, Inc.": 1371285,
    "Enact Holdings, Inc.": 1823529,
    "Riverview Financial Corp": 1590799,
    "Ocwen Financial Corp": 873860,
    "Root, Inc.": 1788882,
    "PENNYMAC": None,          # R2/R3 here are job-posting sourced, not SEC
    "Mercury Insurance": None,  # same
    "Financial Industries Corp": 35733,
    "Ohio Casualty Corp": 73952,
    "Unum Group (UNM, UNMA)": 5513,
    "Sierra Health Services Inc": 754009,
    "Mercury General Corp": 64996,
    "Genworth Financial Inc": 1276520,
    "Ge Financial Assurances Holdings Inc": 1049537,
    "United Insurance Holdings Corp.": 1401521,
}

# R1 gaps that predate SEC full-text search coverage assumptions — resolved
# by direct efts.sec.gov lookup, one filing each.
R1_MANUAL_SOURCE: dict[str, str] = {
    "Sierra Health Services Inc": "https://www.sec.gov/Archives/edgar/data/754009/000075400907000031/form10k.pdf",
    "Mercury General Corp": "https://www.sec.gov/Archives/edgar/data/64996/000006499621000004/mcy-20201231.htm",
}

# Job-posting-sourced rows (not SEC data). Re-confirmed live via web search
# 2026-07-07: Monster.com lists "Sr Java Developer - Drools - Pennymac"
# (Carrollton, TX). Mercury Insurance's original posting could not be
# re-found — left unsourced rather than guessed at.
JOB_POSTING_SOURCE: dict[str, str | None] = {
    "PENNYMAC": "https://www.monster.com/job-openings/sr-java-developer-drools-carrollton-tx--a22f10a8-cbc5-4145-9499-1a60f61ca51a",
    "Mercury Insurance": None,
}


def http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read())


def sec_company_page(cik: int) -> str:
    return (f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
            f"&CIK={cik:010d}&type=10-K&dateb=&owner=include&count=10")


def sec_filing_history_page(cik: int) -> str:
    return (f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
            f"&CIK={cik:010d}&type=&dateb=&owner=include&count=40")


def find_filing_index_url(submissions: dict, cik: int, form: str, date: str) -> str | None:
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accns = recent.get("accessionNumber", [])
    for f, d, acc in zip(forms, dates, accns):
        if f == form and d == date:
            acc_nodash = acc.replace("-", "")
            return f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{acc}-index.htm"
    return None


def parse_r4_form_date(why: str) -> tuple[str, str] | None:
    m = re.search(r"Filed (\S+) on (\d{4}-\d{2}-\d{2})", why)
    return (m.group(1), m.group(2)) if m else None


def parse_r7_contact_name(why: str) -> str | None:
    m = re.search(r"on file \(([^,]+),", why)
    return m.group(1).strip() if m else None


def build_linkedin_index(contacts: dict) -> dict[tuple[str, str], str]:
    idx = {}
    for company, block in contacts.get("companies", {}).items():
        for c in block.get("contacts", []):
            if c.get("linkedin"):
                idx[(company, c["name"])] = f"https://{c['linkedin']}"
    return idx


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    prospects = json.loads(GLASSBOX_PATH.read_text())
    contacts = json.loads(CONTACTS_PATH.read_text())
    linkedin_idx = build_linkedin_index(contacts)

    submissions_cache: dict[int, dict] = {}
    changes = 0
    unresolved: list[str] = []

    def get_submissions(cik: int) -> dict | None:
        if cik in submissions_cache:
            return submissions_cache[cik]
        try:
            data = http_get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
            submissions_cache[cik] = data
            time.sleep(0.3)  # SEC fair-access guideline
            return data
        except Exception as e:
            print(f"  ! submissions fetch failed for CIK {cik}: {e}")
            return None

    for p in prospects:
        name = p["name"]
        cik = CIK_MAP.get(name, "MISSING")
        if cik == "MISSING":
            unresolved.append(name)

        for row in p["trace"]:
            if not row.get("fired") or row.get("source_url"):
                continue
            rid = row["id"]
            why = row.get("why", "")
            new_url = None

            if rid == "R1":
                new_url = R1_MANUAL_SOURCE.get(name)

            elif rid == "R3":
                if name in JOB_POSTING_SOURCE:
                    new_url = JOB_POSTING_SOURCE[name]
                elif cik:
                    new_url = sec_company_page(cik)

            elif rid == "R2":
                if name in JOB_POSTING_SOURCE:
                    new_url = JOB_POSTING_SOURCE[name]

            elif rid == "R4" and cik:
                parsed = parse_r4_form_date(why)
                if parsed:
                    subs = get_submissions(cik)
                    if subs:
                        new_url = find_filing_index_url(subs, cik, parsed[0], parsed[1])

            elif rid == "R6" and cik:
                new_url = sec_filing_history_page(cik)

            elif rid == "R7":
                cname = parse_r7_contact_name(why)
                if cname:
                    new_url = linkedin_idx.get((name, cname))

            if new_url:
                row["source_url"] = new_url
                changes += 1
                print(f"  + {name} | {rid} -> {new_url}")

    print(f"\n{changes} source_url(s) backfilled.")
    if unresolved:
        print(f"No CIK on file for: {', '.join(unresolved)} (expected — job-posting sourced)")

    if dry_run:
        print("\n--dry-run: not writing file.")
        return

    GLASSBOX_PATH.write_text(json.dumps(prospects, indent=2))
    print(f"Wrote {GLASSBOX_PATH}")


if __name__ == "__main__":
    main()
