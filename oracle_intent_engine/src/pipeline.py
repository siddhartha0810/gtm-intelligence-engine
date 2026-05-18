"""
Orchestrates the full scan:
  1. Run all signal scrapers in sequence
  2. Classify each signal (product + phase)
  3. Aggregate by company
  4. Persist to DB
  5. Export CSV + Excel
Returns a summary dict.
"""

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from collections import deque
from src.utils import get_logger, is_valid_company_name
from src import config
from src import database as db
from src import phase_classifier as clf
from src import company_aggregator as agg
from src import exporter
from src import staffing_filter
from src import contact_finder
from src import firmographics
from src import domain_enricher
from src import csv_contacts
from src.signals.indeed_signal import IndeedSignal
from src.signals.linkedin_signal import LinkedInSignal, LINKEDIN_MANUFACTURING_INDUSTRIES
from src.signals.news_signal import NewsSignal
from src.signals.ziprecruiter_signal import ZipRecruiterSignal
from src.signals.adzuna_signal import AdzunaSignal
from src.signals.totaljobs_signal import TotalJobsSignal
from src.signals.cwjobs_signal import CWJobsSignal
from src.signals.oracle_website_signal import OracleWebsiteSignal
from src.signals.home_builders_signal import HomeBuildersSignal
from src.signals.erp_today_signal import ErpTodaySignal
from src.signals.si_casestudy_signal import SICaseStudySignal
from src.signals.procurement_signal import ProcurementSignal
from src.signals.sec_filing_signal import SECFilingSignal
from src.signals.partner_casestudy_signal import PartnerCaseStudySignal
from src.signals.oracle_community_signal import OracleCommunitySignal
from src.signals.oracle_event_signal import OracleEventSignal
from src.signals.company_pages_signal import CompanyPagesSignal

logger = get_logger(__name__)

_scan_lock = threading.Lock()
_stop_requested = False
_log_buffer: deque = deque(maxlen=200)

_current_scan: dict = {
    "status": "idle",
    "progress": "",
    "run_id": None,
    "raw_signals": 0,
    "companies_found": 0,
}


def current_status() -> dict:
    return dict(_current_scan)


def get_log() -> list:
    return list(_log_buffer)


def stop_scan():
    global _stop_requested
    _stop_requested = True
    _log("⛔ Stop requested — finishing current step then stopping...")


def _log(message: str):
    ts = datetime.now().strftime("%H:%M:%S")
    entry = f"[{ts}] {message}"
    _log_buffer.append(entry)
    logger.info(message)


def _is_stopped() -> bool:
    return _stop_requested


def run_scan(
    job_queries: list[str] = None,
    news_queries: list[str] = None,
    location: str = "",
    max_pages: int = None,
    sources: list[str] = None,
    jde_manufacturing_focus: bool = False,
) -> dict:
    global _stop_requested

    if not _scan_lock.acquire(blocking=False):
        return {"error": "A scan is already running."}

    _stop_requested = False
    _log_buffer.clear()

    try:
        job_queries = job_queries or (
            config.JDE_MANUFACTURING_QUERIES if jde_manufacturing_focus
            else config.ORACLE_SEARCH_QUERIES
        )
        news_queries = news_queries or config.NEWS_QUERIES
        sources = sources or [
            "linkedin",
            "news", "oracle_website", "erp_today",
            "oracle_community", "oracle_event",
            "si_casestudy", "partner_casestudy", "company_pages",
            "home_builders",
        ]
        max_pages = max_pages or config.MAX_PAGES

        all_queries = job_queries + news_queries
        run_id = db.start_scan_run(queries=", ".join(all_queries[:10]))
        _current_scan.update({
            "status": "running",
            "run_id": run_id,
            "progress": "Starting...",
            "raw_signals": 0,
            "companies_found": 0,
        })

        focus_label = " [JDE MANUFACTURING FOCUS]" if jde_manufacturing_focus else ""
        _log(f"Scan started{focus_label} — sources: {', '.join(sources)}")
        _log(f"Queries: {len(job_queries)} job queries, {len(news_queries)} news queries")

        scrapers = {
            "indeed":           IndeedSignal(),
            "linkedin":         LinkedInSignal(),
            "ziprecruiter":     ZipRecruiterSignal(),
            "adzuna":           AdzunaSignal(),
            "totaljobs":        TotalJobsSignal(),
            "cwjobs":           CWJobsSignal(),
            "news":             NewsSignal(),
            "oracle_website":   OracleWebsiteSignal(),
            "erp_today":        ErpTodaySignal(),
            "si_casestudy":     SICaseStudySignal(),
            "procurement":      ProcurementSignal(),
            "sec_filing":       SECFilingSignal(),
            "partner_casestudy": PartnerCaseStudySignal(),
            "oracle_community": OracleCommunitySignal(),
            "oracle_event":     OracleEventSignal(),
            "company_pages":    CompanyPagesSignal(),
            "home_builders":    HomeBuildersSignal(),
        }

        raw_signals: list[dict] = []

        # --- Job-posting sources ---
        job_sources = [s for s in sources if s in ("indeed", "linkedin", "ziprecruiter", "adzuna", "totaljobs", "cwjobs")]
        for source_name in job_sources:
            if _is_stopped():
                break
            scraper = scrapers[source_name]
            _current_scan["progress"] = f"Scanning {source_name}..."
            industry_label = " [manufacturing filter]" if jde_manufacturing_focus and source_name == "linkedin" else ""
            _log(f"▶ Starting {source_name.upper()}{industry_label} ({len(job_queries)} queries)")

            for i, query in enumerate(job_queries, 1):
                if _is_stopped():
                    break
                try:
                    if source_name == "linkedin" and jde_manufacturing_focus:
                        results = scraper.fetch(query, location=location, max_pages=max_pages,
                                                industry_filter=LINKEDIN_MANUFACTURING_INDUSTRIES)
                    else:
                        results = scraper.fetch(query, location=location, max_pages=max_pages)
                    raw_signals.extend(results)
                    _current_scan["raw_signals"] = len(raw_signals)
                    _log(f"  [{source_name}] ({i}/{len(job_queries)}) \"{query}\" → {len(results)} results")
                except Exception as e:
                    _log(f"  [{source_name}] ERROR on \"{query}\": {e}")

            _log(f"✓ {source_name.upper()} done — {len(raw_signals)} total signals so far")

        # --- Oracle website ---
        if "oracle_website" in sources and not _is_stopped():
            _current_scan["progress"] = "Scanning oracle.com customer stories..."
            _log("▶ Starting ORACLE.COM (customer stories + press releases)")
            try:
                results = scrapers["oracle_website"].fetch()
                for r in results:
                    if r.get("phase_hint"):
                        r["_phase_override"] = r.pop("phase_hint")
                    if r.get("oracle_product_hint"):
                        r["_product_hint"] = r.pop("oracle_product_hint")
                raw_signals.extend(results)
                _current_scan["raw_signals"] = len(raw_signals)
                _log(f"✓ ORACLE.COM done — {len(results)} customer stories/press releases")
            except Exception as e:
                _log(f"  [oracle_website] ERROR: {e}")

        # --- News source ---
        if "news" in sources and not _is_stopped():
            _current_scan["progress"] = "Scanning news..."
            _log(f"▶ Starting NEWS ({len(news_queries)} queries)")
            for i, query in enumerate(news_queries, 1):
                if _is_stopped():
                    break
                try:
                    results = scrapers["news"].fetch(query, location=location)
                    for r in results:
                        r["signal_type"] = r.get("signal_type", "news_article")
                    raw_signals.extend(results)
                    _current_scan["raw_signals"] = len(raw_signals)
                    _log(f"  [news] ({i}/{len(news_queries)}) \"{query}\" → {len(results)} articles")
                except Exception as e:
                    _log(f"  [news] ERROR on \"{query}\": {e}")
            _log(f"✓ NEWS done")

        # --- ERP Today ---
        if "erp_today" in sources and not _is_stopped():
            _current_scan["progress"] = "Scanning ERP Today..."
            _log("▶ Starting ERP TODAY (oracle ERP news RSS)")
            try:
                results = scrapers["erp_today"].fetch()
                raw_signals.extend(results)
                _current_scan["raw_signals"] = len(raw_signals)
                _log(f"✓ ERP TODAY done — {len(results)} articles")
            except Exception as e:
                _log(f"  [erp_today] ERROR: {e}")

        # --- SI Case Studies ---
        if "si_casestudy" in sources and not _is_stopped():
            _current_scan["progress"] = "Scanning SI case studies..."
            _log("▶ Starting SI CASE STUDIES (Accenture / Deloitte / PwC etc.)")
            try:
                results = scrapers["si_casestudy"].fetch()
                raw_signals.extend(results)
                _current_scan["raw_signals"] = len(raw_signals)
                _log(f"✓ SI CASE STUDIES done — {len(results)} client signals")
            except Exception as e:
                _log(f"  [si_casestudy] ERROR: {e}")

        # --- Partner Case Studies ---
        if "partner_casestudy" in sources and not _is_stopped():
            _current_scan["progress"] = "Scanning partner case studies..."
            _log("▶ Starting PARTNER CASE STUDIES (Oracle Gold/Platinum SIs)")
            try:
                results = scrapers["partner_casestudy"].fetch(location=location)
                raw_signals.extend(results)
                _current_scan["raw_signals"] = len(raw_signals)
                _log(f"✓ PARTNER CASE STUDIES done — {len(results)} client signals")
            except Exception as e:
                _log(f"  [partner_casestudy] ERROR: {e}")

        # --- Oracle Community / Migration Stories ---
        if "oracle_community" in sources and not _is_stopped():
            _current_scan["progress"] = "Scanning Oracle community stories..."
            _log("▶ Starting ORACLE COMMUNITY (migration stories + oracle.com news)")
            try:
                results = scrapers["oracle_community"].fetch(location=location, max_pages=max_pages)
                raw_signals.extend(results)
                _current_scan["raw_signals"] = len(raw_signals)
                _log(f"✓ ORACLE COMMUNITY done — {len(results)} stories")
            except Exception as e:
                _log(f"  [oracle_community] ERROR: {e}")

        # --- Oracle Event Attendance ---
        if "oracle_event" in sources and not _is_stopped():
            _current_scan["progress"] = "Scanning Oracle event signals..."
            _log("▶ Starting ORACLE EVENTS (CloudWorld / OpenWorld attendance)")
            try:
                results = scrapers["oracle_event"].fetch(location=location)
                raw_signals.extend(results)
                _current_scan["raw_signals"] = len(raw_signals)
                _log(f"✓ ORACLE EVENTS done — {len(results)} companies")
            except Exception as e:
                _log(f"  [oracle_event] ERROR: {e}")

        # --- Company Press Releases ---
        if "company_pages" in sources and not _is_stopped():
            _current_scan["progress"] = "Scanning company press releases..."
            _log("▶ Starting COMPANY PAGES (press releases + announcements)")
            try:
                results = scrapers["company_pages"].fetch(location=location)
                raw_signals.extend(results)
                _current_scan["raw_signals"] = len(raw_signals)
                _log(f"✓ COMPANY PAGES done — {len(results)} companies")
            except Exception as e:
                _log(f"  [company_pages] ERROR: {e}")

        # --- Home Builders (1,000+ closings, JDE-focused industries) ---
        if "home_builders" in sources and not _is_stopped():
            _current_scan["progress"] = "Scanning home builders (1,000+ closings)..."
            _log("▶ Starting HOME BUILDERS (1,000+ closings — construction, JDE signals)")
            try:
                results = scrapers["home_builders"].fetch(location=location)
                raw_signals.extend(results)
                _current_scan["raw_signals"] = len(raw_signals)
                _log(f"✓ HOME BUILDERS done — {len(results)} JDE signals")
            except Exception as e:
                _log(f"  [home_builders] ERROR: {e}")

        # --- Procurement / RFP Tenders ---
        if "procurement" in sources and not _is_stopped():
            _current_scan["progress"] = "Scanning procurement tenders..."
            _log("▶ Starting PROCUREMENT (Contracts Finder + SAM.gov + TED EU)")
            try:
                results = scrapers["procurement"].fetch(location=location, max_pages=max_pages)
                raw_signals.extend(results)
                _current_scan["raw_signals"] = len(raw_signals)
                _log(f"✓ PROCUREMENT done — {len(results)} tenders")
            except Exception as e:
                _log(f"  [procurement] ERROR: {e}")

        # --- SEC / Public Filings ---
        if "sec_filing" in sources and not _is_stopped():
            _current_scan["progress"] = "Scanning SEC filings..."
            _log("▶ Starting SEC FILINGS (EDGAR — 10-K/10-Q/8-K)")
            try:
                results = scrapers["sec_filing"].fetch(max_pages=max_pages)
                raw_signals.extend(results)
                _current_scan["raw_signals"] = len(raw_signals)
                _log(f"✓ SEC FILINGS done — {len(results)} companies")
            except Exception as e:
                _log(f"  [sec_filing] ERROR: {e}")

        if _is_stopped():
            _log(f"⛔ Scan stopped by user — {len(raw_signals)} signals collected before stop")

        _log(f"─── Total raw signals collected: {len(raw_signals)} ───")

        # --- Smart staffing filter ---
        # SI partners (IBM, PwC, Wipro etc.) → extract end client → keep as end client signal
        # Pure staffing firms (Robert Half, Randstad etc.) → drop
        # Contractor title signals → extract end client → keep if found, else drop
        raw_signals, removed = staffing_filter.filter_signals(raw_signals)
        if removed:
            _log(f"▶ Staffing filter removed {removed} signals (pure staffing / unresolved SI)")
        _log(f"─── Signals after filter: {len(raw_signals)} ───")

        _current_scan["progress"] = f"Classifying {len(raw_signals)} signals..."
        _log(f"▶ Classifying signals (Oracle product + phase detection)...")

        # --- Classify ---
        classified: list[dict] = []
        for sig in raw_signals:
            result = clf.classify(
                title=sig.get("job_title", ""),
                description=sig.get("description", ""),
                source=sig.get("source", ""),
            )
            if sig.get("_phase_override"):
                result["phase"] = sig.pop("_phase_override")
                result["phase_label"] = clf.PHASE_LABELS.get(result["phase"], result["phase"])
                result["confidence"] = min(result["confidence"] + 0.2, 1.0)
            if sig.get("_product_hint") and sig["_product_hint"] != "Oracle Cloud":
                result["oracle_product"] = sig.pop("_product_hint")
            sig.update(result)
            classified.append(sig)

        _log(f"✓ Classification done")

        # --- Aggregate ---
        _current_scan["progress"] = "Aggregating by company..."
        _log("▶ Aggregating signals by company...")
        companies = agg.aggregate(classified)
        _current_scan["companies_found"] = len(companies)
        _log(f"✓ Aggregation done — {len(companies)} unique companies detected")

        # --- Firmographics enrichment (Wikidata — free, no key) ---
        _current_scan["progress"] = "Enriching company firmographics..."
        _log("▶ Enriching company sizes via Wikidata (parallel)...")
        needs_firmographics = [c for c in companies if not c.get("size")]

        def _enrich_firmographics(company):
            if _is_stopped():
                return
            try:
                data = firmographics.enrich(company["company_name"])
                if data.get("size_band"):
                    company["size"] = data["size_band"]
                if data.get("industry") and not company.get("industry"):
                    company["industry"] = data["industry"]
            except Exception:
                pass

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(_enrich_firmographics, needs_firmographics))

        enriched_count = sum(1 for c in companies if c.get("size"))
        _log(f"✓ Firmographics done — {enriched_count} companies enriched")

        # --- Domain enrichment (Wikidata P856 + DuckDuckGo, free, no key) ---
        _current_scan["progress"] = "Enriching company domains..."
        _log("▶ Enriching company domains (Wikidata + DuckDuckGo, parallel)...")
        needs_domain = [c for c in companies if not c.get("domain")]

        def _enrich_domain(company):
            if _is_stopped():
                return
            try:
                domain = domain_enricher.lookup_domain(company["company_name"])
                if domain:
                    company["domain"] = domain
            except Exception:
                pass

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(_enrich_domain, needs_domain))

        domain_count = sum(1 for c in companies if c.get("domain"))
        _log(f"✓ Domain enrichment done — {domain_count} domains found")

        # Phase breakdown
        from collections import Counter
        phase_counts = Counter(c["phase"] for c in companies)
        for phase, count in phase_counts.most_common():
            label = clf.PHASE_LABELS.get(phase, phase)
            _log(f"   {label}: {count} companies")

        # --- Persist ---
        _current_scan["progress"] = "Saving to database..."
        _log("▶ Saving to database...")
        new_count, known_count = _persist(companies, run_id=run_id)
        _log(f"✓ Database save complete — {new_count} NEW leads, {known_count} already known (skipped)")

        # --- CSV contact matching (all companies, from 280K contacts database) ---
        if csv_contacts.is_available():
            _current_scan["progress"] = "Matching contacts from CSV database..."
            _log("▶ Matching contacts from CSV database...")
            matched_companies = 0
            matched_contacts = 0
            for company in companies:
                try:
                    row = db.get_company_by_name(company["company_name"])
                    if not row:
                        continue
                    contacts = csv_contacts.find_contacts(
                        company["company_name"],
                        domain=company.get("domain", ""),
                    )
                    if contacts:
                        db.save_contacts(row["id"], contacts)
                        matched_companies += 1
                        matched_contacts += len(contacts)
                except Exception as e:
                    _log(f"  [csv_contacts] Error for {company['company_name']}: {e}")
            _log(f"✓ CSV contacts matched — {matched_contacts} contacts across {matched_companies} companies")

        # --- Purge invalid company names from DB (catches any that slipped through) ---
        _current_scan["progress"] = "Cleaning invalid company names..."
        try:
            purged = db.purge_invalid_companies(is_valid_company_name)
            if purged:
                _log(f"▶ Purged {purged} invalid company names from database")
        except Exception as e:
            _log(f"  [purge] Warning: {e}")

        # --- Export ---
        _current_scan["progress"] = "Exporting CSV and Excel..."
        _log("▶ Exporting CSV and Excel...")
        csv_path = exporter.export_csv(companies)
        xlsx_path = exporter.export_excel(companies)
        _log(f"✓ Export complete")

        status = "stopped" if _is_stopped() else "completed"
        db.finish_scan_run(run_id, len(classified), new_count, status=status)
        _current_scan.update({"status": "idle", "progress": "Done.", "companies_found": new_count})

        _log(f"─── Scan {status.upper()} ───")
        _log(f"   Signals: {len(classified)}  |  New companies: {new_count}  |  Already known: {known_count}")

        return {
            "run_id": run_id,
            "total_raw_signals": len(raw_signals),
            "total_classified": len(classified),
            "total_companies": len(companies),
            "csv_path": csv_path,
            "xlsx_path": xlsx_path,
            "completed_at": datetime.now().isoformat(),
        }

    except Exception as e:
        _log(f"✗ Pipeline error: {e}")
        if _current_scan.get("run_id"):
            db.finish_scan_run(_current_scan["run_id"], 0, 0, status="failed")
        _current_scan.update({"status": "idle", "progress": f"Failed: {e}"})
        return {"error": str(e)}

    finally:
        _scan_lock.release()


def run_scan_async(
    job_queries=None, news_queries=None,
    location="", max_pages=None, sources=None,
):
    thread = threading.Thread(
        target=run_scan,
        kwargs=dict(
            job_queries=job_queries,
            news_queries=news_queries,
            location=location,
            max_pages=max_pages,
            sources=sources,
        ),
        daemon=True,
    )
    thread.start()
    return thread


def _persist(companies: list[dict], run_id: int = None) -> tuple[int, int]:
    """Persist companies and signals. Returns (new_count, known_count)."""
    new_count = known_count = 0
    for company in companies:
        try:
            company_id = db.upsert_company(
                name=company["company_name"],
                domain=company.get("domain"),
                industry=company.get("industry"),
                size=company.get("size"),
                location=company.get("location"),
                website=company.get("website"),
                first_scan_run_id=run_id,
            )
            # Only insert signals for companies first discovered in this run.
            # Companies already in DB from previous runs are known leads —
            # inserting their signals again would make them reappear in the feed.
            row = db.get_company_by_id(company_id)
            if row and row.get("first_scan_run_id") != run_id:
                known_count += 1
                continue  # Skip — already a known lead from a previous run
            new_count += 1
            for sig in company.get("signals", []):
                db.insert_signal(
                    company_id=company_id,
                    oracle_product=sig.get("oracle_product", "Oracle (General)"),
                    phase=sig.get("phase", "hiring"),
                    source=sig.get("source", ""),
                    signal_type=sig.get("signal_type", "job_posting"),
                    job_title=sig.get("job_title", ""),
                    evidence=sig.get("description", ""),
                    url=sig.get("url", ""),
                    confidence=sig.get("confidence", 0.5),
                    scan_run_id=run_id,
                )
        except Exception as e:
            _log(f"  Persist error for '{company.get('company_name')}': {e}")
    return new_count, known_count
