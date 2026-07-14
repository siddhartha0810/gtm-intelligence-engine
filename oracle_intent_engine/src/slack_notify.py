"""
slack_notify.py
================
Posts scan-completion summaries to Slack via the same SLACK_WEBHOOK_URL used
by health_monitor.py's alerting. Silent no-op if the webhook isn't configured
so this never blocks a scan.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def notify_scan_complete(*, run_id, status: str, new_count: int, known_count: int,
                          total_signals: int, duration_seconds: float) -> None:
    webhook_url = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return

    try:
        import requests
        emoji = ":white_check_mark:" if status == "completed" else ":warning:"
        mins = round(duration_seconds / 60, 1)
        text = (
            f"{emoji} *Scan {status}* (run #{run_id})\n"
            f"• New companies: {new_count}  |  Already known: {known_count}\n"
            f"• Signals classified: {total_signals}\n"
            f"• Duration: {mins}m"
        )
        payload = {"text": text, "username": "DATA TOOL Monitor", "icon_emoji": ":satellite_antenna:"}
        r = requests.post(webhook_url, json=payload, timeout=10)
        if r.status_code != 200:
            logger.warning("[SlackNotify] scan-complete post failed: %s", r.text)
    except Exception as e:
        logger.error("[SlackNotify] scan-complete post failed: %s", e)
