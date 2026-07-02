"""
health_monitor.py
=================
ARE (Agent Reliability Engineer) pattern — bduffy089/Agentic-GTM-Infrastructure.

Checks that every signal scraper is returning results. A scraper that goes
silent (rate-limited, site layout changed, API key expired) is indistinguishable
from a scraper that scanned and found nothing — both return 0 signals. This
module catches the difference by tracking the last successful result per source
and alerting when a source has been silent for too long.

Usage:
    from src.health_monitor import check_signal_health, get_health_status
    status = get_health_status()          # returns dict for the /api/health/signals endpoint
    check_signal_health(notify=True)      # checks + posts Slack alert if any P0 sources are silent
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# How long a source can be silent before we flag it
_ALERT_THRESHOLDS = {
    "P0_silent_hours": 24,   # P0 sources: alert if silent > 24h
    "P1_silent_hours": 48,   # P1 sources: alert if silent > 48h
    "P2_silent_hours": 72,   # P2 sources: alert if silent > 72h
}

# Signal sources ranked by reliability tier
_SOURCE_TIERS = {
    # P0 — core job-board signals, should fire on every scan
    "indeed":        "P0",
    "linkedin":      "P0",
    "google_jobs":   "P0",
    "adzuna":        "P0",
    # P1 — secondary sources, should fire at least every other scan
    "news":          "P1",
    "ziprecruiter":  "P1",
    "erp_today":     "P1",
    # P2 — contextual / lower frequency expected
    "oracle_website":     "P2",
    "oracle_community":   "P2",
    "oracle_event":       "P2",
    "si_casestudy":       "P2",
    "partner_casestudy":  "P2",
    "company_pages":      "P2",
    "g2_reviews":         "P2",
    "home_builders":      "P2",
}


def _get_last_signal_per_source() -> dict[str, Optional[str]]:
    """
    Query the database for the most recent detected_at timestamp per signal source.
    Returns: {source_name: iso_timestamp_or_None}
    """
    try:
        import oracle_intent_engine.src.database as db
        with db.db_cursor(commit=False) as cur:
            cur.execute("""
                SELECT source, MAX(detected_at) AS last_seen
                FROM oracle_signals
                GROUP BY source
            """)
            rows = cur.fetchall()
            return {r["source"]: r["last_seen"] for r in rows}
    except Exception as e:
        logger.error("[HealthMonitor] DB query failed: %s", e)
        return {}


def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        try:
            return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None


def get_health_status() -> dict:
    """
    Returns a structured health report for all known signal sources.

    Shape:
    {
        "checked_at": "2025-01-01T12:00:00",
        "overall": "healthy" | "degraded" | "critical",
        "sources": {
            "indeed": {
                "tier": "P0",
                "last_seen": "2025-01-01T10:00:00",
                "hours_silent": 2.0,
                "status": "healthy" | "warning" | "critical" | "never_seen"
            },
            ...
        },
        "alerts": ["indeed has been silent for 26h (P0 threshold: 24h)", ...]
    }
    """
    last_seen = _get_last_signal_per_source()
    now = datetime.utcnow()
    sources_status = {}
    alerts = []

    for source, tier in _SOURCE_TIERS.items():
        ts = last_seen.get(source)
        dt = _parse_ts(ts)

        if dt is None:
            hours_silent = None
            status = "never_seen"
        else:
            # Normalize to UTC naive if needed
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            hours_silent = round((now - dt).total_seconds() / 3600, 1)
            threshold = _ALERT_THRESHOLDS[f"{tier}_silent_hours"]
            if hours_silent > threshold:
                status = "critical"
                alerts.append(
                    f"{source} ({tier}) silent for {hours_silent}h "
                    f"(threshold: {threshold}h)"
                )
            elif hours_silent > threshold * 0.75:
                status = "warning"
            else:
                status = "healthy"

        sources_status[source] = {
            "tier":         tier,
            "last_seen":    ts,
            "hours_silent": hours_silent,
            "status":       status,
        }

    # Derive overall status
    statuses = [v["status"] for v in sources_status.values()]
    if "critical" in statuses:
        overall = "critical"
    elif "warning" in statuses or "never_seen" in statuses:
        overall = "degraded"
    else:
        overall = "healthy"

    return {
        "checked_at": now.isoformat(),
        "overall":    overall,
        "sources":    sources_status,
        "alerts":     alerts,
    }


def check_signal_health(notify: bool = True) -> dict:
    """
    Run a health check and optionally post to Slack if any sources are critical.
    Returns the same shape as get_health_status().
    """
    status = get_health_status()

    if notify and status["alerts"]:
        _post_slack_alert(status)

    return status


def _post_slack_alert(status: dict) -> None:
    """Post a Slack webhook message for critical signal sources."""
    webhook_url = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    if not webhook_url:
        logger.info("[HealthMonitor] SLACK_WEBHOOK_URL not set — skipping Slack alert")
        return

    try:
        import requests
        alert_lines = "\n".join(f"• {a}" for a in status["alerts"])
        payload = {
            "text": f"*:warning: Signal Health Alert — {status['overall'].upper()}*\n{alert_lines}\n"
                    f"Check the dashboard: http://localhost:8000/api/health/signals",
            "username":   "DATA TOOL Monitor",
            "icon_emoji": ":satellite_antenna:",
        }
        r = requests.post(webhook_url, json=payload, timeout=10)
        if r.status_code != 200:
            logger.warning("[HealthMonitor] Slack post failed: %s", r.text)
    except Exception as e:
        logger.error("[HealthMonitor] Slack alert failed: %s", e)


def run_health_check_loop(interval_minutes: int = 15) -> None:
    """
    Background daemon loop — called once, runs forever.
    Start via threading.Thread(target=run_health_check_loop, daemon=True).start()
    """
    logger.info("[HealthMonitor] Starting health check loop (every %dm)", interval_minutes)
    while True:
        try:
            result = check_signal_health(notify=True)
            logger.info(
                "[HealthMonitor] %s — %d sources checked, %d alerts",
                result["overall"], len(result["sources"]), len(result["alerts"]),
            )
        except Exception as e:
            logger.error("[HealthMonitor] Loop error: %s", e)
        time.sleep(interval_minutes * 60)
