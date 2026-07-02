"""
metrics.py
==========
Prometheus metrics for the Oracle Intent Engine pipeline.

Grafana integration — expose these via:
  Flask:   PrometheusMetrics(app) from prometheus_flask_exporter
  FastAPI: Instrumentator().instrument(app).expose(app)

Dashboard panels (copy into Grafana):
  - Signals/min by type:       rate(signals_detected_total[5m])
  - Apollo credits today:      increase(apollo_credits_used_total[24h])
  - ZeroBounce credits today:  increase(zerobounce_credits_used_total[24h])
  - Email valid rate:          rate(emails_validated_total{result="valid"}[1h]) / rate(emails_validated_total[1h])
  - Scan in progress:          scan_in_progress
  - Companies found per run:   last_scan_companies_found

Alert thresholds:
  - apollo_credits_used_total[24h] > 800  → near daily limit
  - zerobounce_credits_used_total[24h] > 500  → near daily budget
  - scan_in_progress > 0 for > 7200 seconds  → hung scan
  - last_scan_companies_found < 5  → signal sources degraded
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Lazy-import prometheus_client so the app still starts without it
try:
    from prometheus_client import Counter, Gauge, Histogram, REGISTRY

    # ── Signal detection ───────────────────────────────────────────────────────
    signals_detected_total = Counter(
        "signals_detected_total",
        "Intent signals found across all sources",
        ["signal_type", "phase", "source"],
    )
    companies_found_total = Counter(
        "companies_found_total",
        "Unique companies added to the database per run",
    )
    staffing_filtered_total = Counter(
        "staffing_filtered_total",
        "Signals removed by staffing_filter.py (not end-user companies)",
    )
    p0_signals_total = Counter(
        "p0_signals_total",
        "P0-tier signals detected (48-hour response window)",
    )

    # ── Enrichment pipeline ────────────────────────────────────────────────────
    contacts_enriched_total = Counter(
        "contacts_enriched_total",
        "Contacts successfully enriched with email/title",
        ["source"],  # apollo / zoominfo / apify / master_leads
    )
    emails_validated_total = Counter(
        "emails_validated_total",
        "Emails processed by ZeroBounce",
        ["result"],  # valid / invalid / catch_all / unknown / do_not_mail
    )
    zerobounce_credits_used = Counter(
        "zerobounce_credits_used_total",
        "ZeroBounce email validation credits consumed",
    )
    apollo_credits_used = Counter(
        "apollo_credits_used_total",
        "Apollo people-reveal credits consumed",
    )
    apollo_requests_total = Counter(
        "apollo_requests_total",
        "Apollo API calls made",
        ["endpoint", "status"],  # status: success / rate_limited / error
    )
    maigret_enrichments_total = Counter(
        "maigret_enrichments_total",
        "LinkedIn URLs found via maigret OSINT",
    )

    # ── HubSpot sync ──────────────────────────────────────────────────────────
    hubspot_pushes_total = Counter(
        "hubspot_pushes_total",
        "Records pushed to HubSpot",
        ["entity_type", "action"],  # entity_type: company/contact, action: created/updated
    )

    # ── Pipeline health gauges ────────────────────────────────────────────────
    scan_in_progress = Gauge(
        "scan_in_progress",
        "1 while a signal scan is actively running, 0 otherwise",
    )
    last_scan_duration_seconds = Gauge(
        "last_scan_duration_seconds",
        "Wall-clock duration of the most recently completed scan",
    )
    last_scan_companies_found = Gauge(
        "last_scan_companies_found",
        "Number of new companies found in the most recently completed scan",
    )
    last_scan_signals_found = Gauge(
        "last_scan_signals_found",
        "Number of classified signals in the most recently completed scan",
    )

    # ── API latency histograms ─────────────────────────────────────────────────
    apollo_request_latency = Histogram(
        "apollo_request_duration_seconds",
        "Apollo API call round-trip latency",
        buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
    )
    zerobounce_request_latency = Histogram(
        "zerobounce_request_duration_seconds",
        "ZeroBounce API call latency",
        buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0],
    )

    METRICS_AVAILABLE = True
    logger.debug("[Metrics] Prometheus metrics registered")

except ImportError:
    # prometheus_client not installed — all metrics become no-ops
    METRICS_AVAILABLE = False
    logger.info("[Metrics] prometheus_client not installed — metrics disabled. "
                "Run: pip install prometheus-client prometheus-flask-exporter")

    class _Noop:
        """Stub that absorbs any attribute access and any call."""
        def __getattr__(self, _): return self
        def __call__(self, *a, **kw): return self
        def labels(self, **kw): return self
        def inc(self, n=1): pass
        def set(self, v): pass
        def observe(self, v): pass
        def time(self): return self
        def __enter__(self): return self
        def __exit__(self, *a): pass

    _noop = _Noop()

    signals_detected_total     = _noop
    companies_found_total      = _noop
    staffing_filtered_total    = _noop
    p0_signals_total           = _noop
    contacts_enriched_total    = _noop
    emails_validated_total     = _noop
    zerobounce_credits_used    = _noop
    apollo_credits_used        = _noop
    apollo_requests_total      = _noop
    maigret_enrichments_total  = _noop
    hubspot_pushes_total       = _noop
    scan_in_progress           = _noop
    last_scan_duration_seconds = _noop
    last_scan_companies_found  = _noop
    last_scan_signals_found    = _noop
    apollo_request_latency     = _noop
    zerobounce_request_latency = _noop
