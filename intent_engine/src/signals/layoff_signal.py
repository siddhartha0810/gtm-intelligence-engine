"""
Layoff signal — layoffs.fyi's public Airtable shared view (free, no key).

Why this is a buying signal: a layoff at a B2B SaaS company is cost pressure
made public — the moment the retain-vs-acquire math flips toward retention
tooling (every lost customer must now be replaced with a smaller GTM team).
It is the private-company analog of an 8-K restructuring disclosure: WARN-Act
filings and press coverage feed layoffs.fyi within days, and the dataset is
structured (company, headcount cut, %, date, industry, stage, source link)
rather than free text.

Fetch flow (3 HTTP requests total per run, no scraping loops):
  1. GET layoffs.fyi           -> find the Airtable embed URL (app…/shr…)
  2. GET the embed page        -> extract the signed readSharedViewData URL
                                  (Airtable issues a fresh signature per
                                  embed load — nothing here is hardcoded)
  3. GET readSharedViewData    -> one JSON payload, ~4.5k rows

Confidence: 0.60 — the layoff is verified fact with a press-source link, but
company-level ICP fit still needs the usual downstream checks (a laid-off
restaurant chain is not a QuadSci prospect; the Industry column narrows this
but doesn't settle it). Never set higher without a second signal type — per
.claude/rules/signals.md, this is "strong indicator", not "explicit intent".
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

import requests

from src.signals.base_signal import BaseSignal
from src.utils import get_logger, truncate

logger = get_logger(__name__)

_UA = {"User-Agent": "Mozilla/5.0 (compatible; gtm-intent-research/1.0)"}
_TIMEOUT = 30
_LAYOFFS_FYI = "https://layoffs.fyi/"

# Industry values on layoffs.fyi that plausibly contain B2B-SaaS ICP
# companies. Rows outside these are dropped BEFORE emitting — a consumer
# retailer's layoff is real cost pressure but not for a SaaS-retention ICP.
_RELEVANT_INDUSTRIES = {
    "data", "infrastructure", "security", "marketing", "sales", "hr",
    "product", "support", "ai", "aerospace", "crypto", "finance", "fintech",
    "healthcare", "legal", "logistics", "media", "real estate", "recruiting",
    "retail", "education", "energy", "food", "hardware", "other", "travel",
    "transportation", "consumer", "construction", "manufacturing",
}
# Kept intentionally broad — the staffing filter, phase classifier, and
# glassbox scorer do the real narrowing. Set LAYOFF_STRICT_INDUSTRIES=True
# in a future pass if precision becomes the bottleneck.


def fetch_layoff_rows(window_days: int = 180) -> list[dict]:
    """Fetch + parse the layoffs.fyi tracker into plain dicts:
    {company, laid_off, percentage, date (datetime), industry, stage,
     country, source_url}. Shared by LayoffSignal.fetch() and
    run_glassbox's cost-pressure corroboration. Returns [] on any failure —
    never raises."""
    try:
        front = requests.get(_LAYOFFS_FYI, headers=_UA, timeout=_TIMEOUT).text
        m = re.search(r"airtable\.com/embed/(app[a-zA-Z0-9]+)/(shr[a-zA-Z0-9]+)", front)
        if not m:
            logger.warning("[layoffs] no Airtable embed found on layoffs.fyi")
            return []
        app_id, share_id = m.group(1), m.group(2)

        embed = requests.get(f"https://airtable.com/embed/{app_id}/{share_id}",
                             headers=_UA, timeout=_TIMEOUT).text
        u = re.search(r'urlWithParams["\']?\s*[:=]\s*["\']([^"\']*readSharedViewData[^"\']*)', embed)
        if not u:
            logger.warning("[layoffs] embed page had no readSharedViewData URL "
                           "(Airtable embed format changed)")
            return []
        url = u.group(1).encode().decode("unicode_escape")
        if url.startswith("/"):
            url = "https://airtable.com" + url

        resp = requests.get(url, headers={
            **_UA,
            "x-airtable-application-id": app_id,
            "x-requested-with": "XMLHttpRequest",
            "x-time-zone": "America/Chicago",
        }, timeout=_TIMEOUT)
        resp.raise_for_status()
        table = resp.json()["data"]["table"]
    except Exception as e:
        logger.warning("[layoffs] fetch failed: %s", e)
        return []

    col_name: dict[str, str] = {}
    choices: dict[str, str] = {}  # select-option id -> human label (global; ids are unique)
    for col in table.get("columns", []):
        col_name[col["id"]] = col.get("name", "")
        for ch in (col.get("typeOptions") or {}).get("choices", {}).values():
            choices[ch["id"]] = ch.get("name", "")

    def _label(v):
        if isinstance(v, list):
            v = v[0] if v else ""
        return choices.get(v, v) if isinstance(v, str) else v

    cutoff = datetime.now() - timedelta(days=window_days)
    rows = []
    for r in table.get("rows", []):
        cells = {col_name.get(k, k): v for k, v in (r.get("cellValuesByColumnId") or {}).items()}
        company = (cells.get("Company") or "").strip() if isinstance(cells.get("Company"), str) else ""
        date_raw = cells.get("Date") or ""
        try:
            when = datetime.fromisoformat(str(date_raw).replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            continue
        if not company or when < cutoff:
            continue
        rows.append({
            "company":    company,
            "laid_off":   cells.get("# Laid Off"),
            "percentage": cells.get("%"),
            "date":       when,
            "industry":   _label(cells.get("Industry", "")),
            "stage":      _label(cells.get("Stage", "")),
            "country":    _label(cells.get("Country", "")),
            "source_url": cells.get("Source") or "",
        })
    logger.info("[layoffs] %d layoff events within %dd window", len(rows), window_days)
    return rows


class LayoffSignal(BaseSignal):
    source_name = "layoffs"

    def fetch(self, query: str = "", location: str = "", max_pages: int = 3,
              window_days: int = 180) -> list[dict]:
        """Emit one signal per recent layoff event at a relevant-industry
        company. `query`/`location`/`max_pages` accepted for interface
        parity but unused — the dataset is one bounded fetch, not a paged
        search. Description text deliberately contains the phrases
        campaign cost_pressure rules detect ("laid off", "workforce
        reduction") so campaign-keyword classification keeps these rows."""
        signals = []
        try:
            for row in fetch_layoff_rows(window_days=window_days):
                industry = (row["industry"] or "").lower()
                if industry and _RELEVANT_INDUSTRIES and industry not in _RELEVANT_INDUSTRIES:
                    continue
                n = row["laid_off"]
                pct = row["percentage"]
                pct_txt = f" ({round(pct * 100)}% of workforce)" if isinstance(pct, (int, float)) else ""
                n_txt = f"{int(n)} employees" if isinstance(n, (int, float)) else "an undisclosed number of employees"
                title = f"Workforce reduction: {n_txt}{pct_txt}"
                desc = (f"{row['company']} laid off {n_txt}{pct_txt} on "
                        f"{row['date']:%Y-%m-%d}. Industry: {row['industry'] or 'n/a'}; "
                        f"stage: {row['stage'] or 'n/a'}. A public workforce reduction is "
                        f"cost pressure — retention economics now outweigh acquisition.")
                signals.append(self._make_signal(
                    company_name=row["company"],
                    job_title=title,
                    description=truncate(desc, 2000),
                    url=row["source_url"],
                    location=row["country"] or "",
                    posted_date=f"{row['date']:%Y-%m-%d}",
                    extra={
                        "signal_type": "layoff",
                        "laid_off":    row["laid_off"],
                        "percentage":  row["percentage"],
                        "industry":    row["industry"],
                        "stage":       row["stage"],
                        "evidence":    desc,
                    },
                ))
        except Exception as e:
            logger.error("[layoffs] emit failed: %s", e)
        logger.info("[layoffs] %d layoff signals emitted", len(signals))
        return signals
