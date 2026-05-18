"""
audit.py
========
Tracks what happened at each stage of the pipeline and writes a CSV log.

The audit log records:
  - A summary row after every stage (how many emails/LinkedIn URLs exist)
  - Individual lead-level events (optional, for debugging)

Output: output/audit_log.csv
"""

from typing import Any, Dict, List, Optional
import pandas as pd
from .utils import now_iso


class AuditLog:
    """
    Collects log entries throughout the pipeline run and saves them to CSV at the end.

    Usage:
        audit = AuditLog()
        audit.log_stage_summary("cleaned", df)   # called automatically by pipeline.py
        audit.save("output/audit_log.csv")        # called at the very end
    """

    def __init__(self) -> None:
        # All log entries are stored in memory as a list of dicts,
        # then written to CSV in one shot at the end
        self.rows: List[Dict[str, Any]] = []

    def add(
        self,
        lead_id: str,
        stage: str,
        status: str,
        message: str = "",
        vendor: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Add a single lead-level log entry.
        Useful for recording which vendor found what for a specific lead.
        """
        self.rows.append({
            "timestamp": now_iso(),
            "lead_id":   lead_id,
            "stage":     stage,
            "vendor":    vendor,
            "status":    status,
            "message":   message,
            "metadata":  metadata or {},
        })

    def log_stage_summary(self, stage: str, df: pd.DataFrame) -> None:
        """
        Append a summary row after each pipeline stage.
        Records total rows, how many have emails, how many have LinkedIn URLs.
        This is what you see in output/audit_log.csv as the "__summary__" rows.
        """
        emails   = int((df["email"].astype(str).str.strip() != "").sum())   if "email"       in df.columns else 0
        linkedin = int((df["linkedin_url"].astype(str).str.strip() != "").sum()) if "linkedin_url" in df.columns else 0

        self.rows.append({
            "timestamp": now_iso(),
            "lead_id":   "__summary__",
            "stage":     stage,
            "vendor":    "",
            "status":    "summary",
            "message":   f"rows={len(df)}, emails={emails}, linkedin={linkedin}",
            "metadata":  {
                "rows":            len(df),
                "emails_found":    emails,
                "linkedin_found":  linkedin,
            },
        })

    def save(self, path: str) -> None:
        """Write all collected log entries to a CSV file."""
        pd.DataFrame(self.rows).to_csv(path, index=False)
