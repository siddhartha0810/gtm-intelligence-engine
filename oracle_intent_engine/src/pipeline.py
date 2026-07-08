"""Orchestrates the full Oracle intent scan: scrape, classify, aggregate, persist, export."""

import threading
import time as _time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from collections import deque
from src.utils import get_logger, is_valid_company_name
from src import config
from src import metrics as _metrics
from src import tech_profiles
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
from src.signals.g2_reviews_signal import G2ReviewsSignal
from src.signals.agentic_harvester_signal import AgenticHarvesterSignal
from src.signals.ats_signal import ATSSignal

logger = get_logger(__name__)

_scan_lock = threading.Lock()
_stop_requested = False
_log_buffer: deque = deque(maxlen=200)

# Ordered, high-level pipeline stages — surfaced to the frontend as a live
# checklist (see /scan/status "stages" field) rather than the ~15 individual
# per-source scrapers, which would be too granular to read as a workflow.
STAGE_DEFS: list[tuple[str, str]] = [
    ("fetch",         "Fetch signals from sources"),
    ("filter",        "Filter staffing agencies"),
    ("classify",       "Classify product + buying phase"),
    ("aggregate",      "Aggregate signals by company"),
    ("firmographics",  "Enrich company size & industry"),
    ("domains",        "Enrich company domains"),
    ("persist",        "Save companies & signals"),
    ("contacts",        "Match existing contacts (free)"),
    ("export",          "Export CSV & Excel"),
]

_current_scan: dict = {
    "status": "idle",
    "progress": "",
    "run_id": None,
    "raw_signals": 0,
    "companies_found": 0,
    "stages": {},
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

def _stage(stage_id: str, status: str) -> None:
    """status: 'running' | 'done' | 'error'. See STAGE_DEFS for the fixed order."""
    _current_scan.setdefault("stages", {})[stage_id] = status

def run_scan(
    job_queries: list[str] = None,
    news_queries: list[str] = None,
    location: str = "",
    max_pages: int = None,
    sources: list[str] = None,
    jde_manufacturing_focus: bool = False,
    industry_filter: str | None = None,
    campaign_id: int | None = None,
    campaign_keywords: list[str] | None = None,
) -> dict:
    """
    industry_filter: LinkedIn industry-code filter (e.g. "96,4,80,22,10,74,57"
    for manufacturing) — independent of jde_manufacturing_focus so any custom
    job_queries list can also carry its own vertical/industry targeting.
    """
    global _stop_requested

    if not _scan_lock.acquire(blocking=False):
        return {"error": "A scan is already running."}

    _stop_requested = False
    _log_buffer.clear()
    _scan_start_time = _time.monotonic()
    _metrics.scan_in_progress.set(1)

    try:
        job_queries = job_queries or (
            config.JDE_MANUFACTURING_QUERIES if jde_manufacturing_focus
            else tech_profiles.get_active_search_queries()
        )
        news_queries = news_queries or config.NEWS_QUERIES
        sources = sources or [
            "linkedin",
            "news", "oracle_website", "erp_today",
            "oracle_community", "oracle_event",
            "si_casestudy", "partner_casestudy", "company_pages",
            "home_builders",
            "g2_reviews",
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
            "stages": {sid: "pending" for sid, _ in STAGE_DEFS},
        })

        focus_label = " [JDE MANUFACTURING FOCUS]" if jde_manufacturing_focus else ""
        _log(f"Scan started{focus_label} — sources: {', '.join(sources)}")
        _log(f"Queries: {len(job_queries)} job queries, {len(news_queries)} news queries")

        _stage("fetch", "running")

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
            "g2_reviews":       G2ReviewsSignal(),
            "agentic_harvester": AgenticHarvesterSignal(),
            "ats":              ATSSignal(),
        }

        raw_signals: list[dict] = []

        # job-posting sources
        job_sources = [s for s in sources if s in ("indeed", "linkedin", "ziprecruiter", "adzuna", "totaljobs", "cwjobs")]
        for source_name in job_sources:
            if _is_stopped():
                break
            scraper = scrapers[source_name]
            _current_scan["progress"] = f"Scanning {source_name}..."
            effective_industry_filter = industry_filter or (LINKEDIN_MANUFACTURING_INDUSTRIES if jde_manufacturing_focus else None)
            industry_label = " [industry filter]" if effective_industry_filter and source_name == "linkedin" else ""
            _log(f"▶ Starting {source_name.upper()}{industry_label} ({len(job_queries)} queries)")

            for i, query in enumerate(job_queries, 1):
                if _is_stopped():
                    break
                try:
                    if source_name == "linkedin" and effective_industry_filter:
                        results = scraper.fetch(query, location=location, max_pages=max_pages,
                                                industry_filter=effective_industry_filter)
                    else:
                        results = scraper.fetch(query, location=location, max_pages=max_pages)
                    raw_signals.extend(results)
                    _current_scan["raw_signals"] = len(raw_signals)
                    _log(f"  [{source_name}] ({i}/{len(job_queries)}) \"{query}\" → {len(results)} results")
                except Exception as e:
                    _log(f"  [{source_name}] ERROR on \"{query}\": {e}")

            _log(f"✓ {source_name.upper()} done — {len(raw_signals)} total signals so far")

        # oracle website
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
                if len(results) == 0:
                    _log("⚠ ORACLE.COM done — 0 signals. oracle.com WAF likely blocked direct scraping; Bing RSS may be blocked by network/proxy on this machine.")
                else:
                    _log(f"✓ ORACLE.COM done — {len(results)} customer stories/press releases")
            except Exception as e:
                _log(f"  [oracle_website] ERROR: {e}")

        # news source
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

        # erp today
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

        # si case studies
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

        # partner case studies
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

        # oracle community / migration stories
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

        # oracle event attendance
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

        # company press releases
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

        # home builders (1,000+ closings, jde-focused industries)
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

        # G2 / Capterra reviews — confirmed Oracle product users
        if "g2_reviews" in sources and not _is_stopped():
            _current_scan["progress"] = "Scanning G2/Capterra reviews (confirmed Oracle users)..."
            _log("▶ Starting G2/CAPTERRA REVIEWS (confirmed active Oracle deployments)")
            try:
                results = scrapers["g2_reviews"].fetch(location=location)
                raw_signals.extend(results)
                _current_scan["raw_signals"] = len(raw_signals)
                _log(f"✓ G2/CAPTERRA done — {len(results)} confirmed-user signals")
            except Exception as e:
                _log(f"  [g2_reviews] ERROR: {e}")

        # ATS boards — first-party open job JSON, ~0% block rate, highest signal
        if "ats" in sources and not _is_stopped():
            _current_scan["progress"] = "Scanning ATS boards (Greenhouse/Lever/Ashby/SmartRecruiters)..."
            ats_keywords = campaign_keywords or config.ATS_DEFAULT_INTENT_KEYWORDS
            _log(f"▶ Starting ATS ({len(config.ATS_BOARDS)} boards, "
                 f"{len(ats_keywords)} intent keywords)")
            try:
                results = scrapers["ats"].fetch(location=location, max_pages=max_pages,
                                                keywords=ats_keywords)
                raw_signals.extend(results)
                _current_scan["raw_signals"] = len(raw_signals)
                _log(f"✓ ATS done — {len(results)} first-party hiring signals")
            except Exception as e:
                _log(f"  [ats] ERROR: {e}")

        # agentic harvester — arbitrary watch-list URLs, no dedicated parser needed
        if "agentic_harvester" in sources and not _is_stopped():
            _current_scan["progress"] = "Running agentic harvester on watch-list URLs..."
            _log("▶ Starting AGENTIC HARVESTER (config.AGENTIC_HARVESTER_URLS)")
            try:
                results = scrapers["agentic_harvester"].fetch(location=location, max_pages=max_pages)
                raw_signals.extend(results)
                _current_scan["raw_signals"] = len(raw_signals)
                _log(f"✓ AGENTIC HARVESTER done — {len(results)} signals")
            except Exception as e:
                _log(f"  [agentic_harvester] ERROR: {e}")

        # procurement / rfp tenders
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

        # sec / public filings
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
        _stage("fetch", "done")

        # smart staffing filter
        # staffing filter: drop pure agencies, extract end clients from SI/contractor signals
        _stage("filter", "running")
        raw_signals, removed = staffing_filter.filter_signals(raw_signals)
        if removed:
            _log(f"▶ Staffing filter removed {removed} signals (pure staffing / unresolved SI)")
        _log(f"─── Signals after filter: {len(raw_signals)} ───")
        _stage("filter", "done")

        _current_scan["progress"] = f"Classifying {len(raw_signals)} signals..."
        _log(f"▶ Classifying signals (Oracle product + phase detection)...")
        _stage("classify", "running")

        # classify
        classified: list[dict] = []
        for sig in raw_signals:
            result = clf.classify(
                title=sig.get("job_title", ""),
                description=sig.get("description", ""),
                source=sig.get("source", ""),
                campaign_keywords=campaign_keywords,
            )
            if sig.get("_phase_override"):
                result["phase"] = sig.pop("_phase_override")
                result["phase_label"] = clf.PHASE_LABELS.get(result["phase"], result["phase"])
                result["confidence"] = min(result["confidence"] + 0.2, 1.0)

            _metrics.signals_detected_total.labels(
                signal_type=sig.get("signal_type", "unknown"),
                phase=result.get("phase", "unknown"),
                source=sig.get("source", "unknown"),
            ).inc()
            if sig.get("_product_hint") and sig["_product_hint"] != "Oracle Cloud":
                hint = sig.pop("_product_hint")
                # Normalize hint against active taxonomy canonical names so stale
                # scraper-supplied names (e.g. "JD Edwards") don't bypass the taxonomy.
                active_names, _ = clf._get_products()
                if hint in active_names:
                    result["oracle_product"] = hint
                # else: classifier result stands — hint is an old/unknown name
            sig.update(result)
            classified.append(sig)

        # Discard signals where no specific Oracle product could be identified.
        # These add noise and inflate Oracle (General) counts in the UI.
        before_filter = len(classified)
        classified = [s for s in classified if s.get("oracle_product")]
        dropped = before_filter - len(classified)
        if dropped:
            _log(f"  Dropped {dropped} unclassified signals (no specific Oracle product detected)")
        _log(f"✓ Classification done — {len(classified)} signals with identified products")
        _stage("classify", "done")

        # aggregate
        _current_scan["progress"] = "Aggregating by company..."
        _log("▶ Aggregating signals by company...")
        _stage("aggregate", "running")
        companies = agg.aggregate(classified)
        _current_scan["companies_found"] = len(companies)
        _log(f"✓ Aggregation done — {len(companies)} unique companies detected")
        _stage("aggregate", "done")

        # firmographics enrichment (wikidata — free, no key)
        _current_scan["progress"] = "Enriching company firmographics..."
        _log("▶ Enriching company sizes via Wikidata (parallel)...")
        _stage("firmographics", "running")
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
        _stage("firmographics", "done")

        # domain enrichment (wikidata p856 + duckduckgo, free, no key)
        _current_scan["progress"] = "Enriching company domains..."
        _log("▶ Enriching company domains (Wikidata + DuckDuckGo, parallel)...")
        _stage("domains", "running")
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
        _stage("domains", "done")

        from collections import Counter
        phase_counts = Counter(c["phase"] for c in companies)
        for phase, count in phase_counts.most_common():
            label = clf.PHASE_LABELS.get(phase, phase)
            _log(f"   {label}: {count} companies")

        # persist
        _current_scan["progress"] = "Saving to database..."
        _log("▶ Saving to database...")
        _stage("persist", "running")
        new_count, known_count = _persist(companies, run_id=run_id)
        _log(f"✓ Database save complete — {new_count} NEW leads, {known_count} already known (skipped)")

        # Set target_product (JD Edwards, Oracle Fusion, ...) from each company's
        # dominant signal so enrichment can tag every contact with the product to pitch.
        try:
            filled = db.backfill_target_product()
            if filled:
                _log(f"✓ Target product set for {filled} companies from their signals")
        except Exception as e:
            _log(f"  [target_product] Warning: {e}")
        _stage("persist", "done")

        # contacts_master pre-check (FREE — runs before any paid enrichment):
        # every scanned company is checked against the Salesforce export first.
        # Matches get their contacts saved immediately, so those companies are
        # already satisfied and never appear in the paid-enrichment queue.
        # Companies that already have contacts in the DB are skipped entirely.
        _current_scan["progress"] = "Checking contacts_master for known contacts..."
        _log("▶ Checking scanned companies against contacts_master (no credits used)...")
        _stage("contacts", "running")
        master_companies = master_contacts = 0
        from src.apollo_enrichment import master_rows_to_contacts, _score_contacts
        for company in companies:
            if _is_stopped():
                break
            try:
                row = db.get_company_by_name(company["company_name"])
                if not row:
                    continue  # failed validation gate — was never saved
                if (row.get("contact_count") or 0) > 0:
                    continue  # already has contacts — no enrichment needed
                master_rows = db.get_master_leads_by_company(row["name"])
                if not master_rows:
                    continue
                to_save = master_rows_to_contacts(master_rows)
                to_save = _score_contacts(to_save, row.get("target_product") or "")
                db.save_contacts(row["id"], to_save)
                master_companies += 1
                master_contacts  += len(to_save)
            except Exception as e:
                _log(f"  [contacts_master] Error for {company['company_name']}: {e}")
        _log(f"✓ contacts_master check done — {master_contacts} contacts pulled for "
             f"{master_companies} companies (these skip paid enrichment)")

        # csv contact matching (all companies, from 280k contacts database)
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
        _stage("contacts", "done")

        # purge invalid company names from db (catches any that slipped through)
        _current_scan["progress"] = "Cleaning invalid company names..."
        try:
            purged = db.purge_invalid_companies(is_valid_company_name)
            if purged:
                _log(f"▶ Purged {purged} invalid company names from database")
        except Exception as e:
            _log(f"  [purge] Warning: {e}")

        # export
        _current_scan["progress"] = "Exporting CSV and Excel..."
        _log("▶ Exporting CSV and Excel...")
        _stage("export", "running")
        csv_path = exporter.export_csv(companies)
        xlsx_path = exporter.export_excel(companies)
        _log(f"✓ Export complete")
        _stage("export", "done")

        status = "stopped" if _is_stopped() else "completed"
        db.finish_scan_run(run_id, len(classified), new_count, status=status)
        _current_scan.update({"status": "idle", "progress": "Done.", "companies_found": new_count})

        if campaign_id:
            try:
                db.update_campaign_run_stats(
                    campaign_id=campaign_id,
                    run_id=run_id,
                    signals=len(classified),
                    companies=new_count,
                )
            except Exception:
                pass

        # Prometheus metrics
        _metrics.scan_in_progress.set(0)
        _metrics.last_scan_duration_seconds.set(_time.monotonic() - _scan_start_time)
        _metrics.last_scan_companies_found.set(new_count)
        _metrics.last_scan_signals_found.set(len(classified))
        _metrics.companies_found_total.inc(new_count)

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
        # Whichever stage was mid-flight when this fired should show as errored,
        # not stuck on "running" forever in the frontend's checklist.
        stages = _current_scan.get("stages", {})
        for sid, sstatus in stages.items():
            if sstatus == "running":
                stages[sid] = "error"
        _current_scan.update({"status": "idle", "progress": f"Failed: {e}"})
        _metrics.scan_in_progress.set(0)
        return {"error": str(e)}

    finally:
        _scan_lock.release()

def _persist(companies: list[dict], run_id: int = None) -> tuple[int, int]:
    """Persist companies and signals. Returns (new_count, known_count)."""
    from rapidfuzz import fuzz as _fuzz

    new_count = known_count = 0
    signal_company_ids: list[int] = []

    # Load existing company names once for fuzzy dedup.
    # Prevents name variants (e.g. "Ford Motor Company" vs "Ford") creating duplicates.
    existing_names: list[str] = db.get_all_company_names()

    for company in companies:
        # Final gate: never write an unreliable company name to the database.
        # Signals already validate at scrape time, but aggregation can still
        # produce headline fragments — this is the last line of defence.
        if not is_valid_company_name(company.get("company_name", "")):
            _log(f"  Skipped invalid company name: '{company.get('company_name')}'")
            continue
        try:
            # Fuzzy-match scraped name against existing DB names (85% threshold).
            # Catches variants like "Ford Motor Company" → "Ford", so we don't
            # create a second DB entry and bypass the known-company check.
            # Update in-place so the contacts_master loop below uses canonical name.
            for existing in existing_names:
                if _fuzz.token_sort_ratio(company["company_name"], existing) >= 85:
                    company["company_name"] = existing
                    break

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
                oracle_product = sig.get("oracle_product")
                if not oracle_product or oracle_product == "Oracle (General)":
                    continue  # skip unclassified signals
                db.insert_signal(
                    company_id=company_id,
                    oracle_product=oracle_product,
                    phase=sig.get("phase", "hiring"),
                    source=sig.get("source", ""),
                    signal_type=sig.get("signal_type", "job_posting"),
                    job_title=sig.get("job_title", ""),
                    evidence=sig.get("description", ""),
                    url=sig.get("url", ""),
                    confidence=sig.get("confidence", 0.5),
                    scan_run_id=run_id,
                )
                signal_company_ids.append(company_id)
        except Exception as e:
            _log(f"  Persist error for '{company.get('company_name')}': {e}")

    # Batch-update signal_count once per scan instead of per-insert (avoids N+1).
    if signal_company_ids:
        try:
            db.batch_update_signal_counts(signal_company_ids)
        except Exception as e:
            _log(f"  Warning: batch_update_signal_counts failed: {e}")

    return new_count, known_count
