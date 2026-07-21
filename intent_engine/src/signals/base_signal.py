"""
base_signal.py
==============
Abstract base class that every signal scraper must inherit from.

PURPOSE:
  Defines the contract between the signal scrapers and the scan pipeline.
  Every scraper (IndeedSignal, NewsSignal, AdzunaSignal, etc.) inherits from
  BaseSignal and implements fetch() which returns a list of raw signal dicts.

HOW IT FITS IN THE SYSTEM:
  scan_worker.py iterates over all registered scrapers, calls fetch() on each,
  then passes the results to pipeline.py → phase_classifier.py → database.py.

  New signal checklist (from signals.md):
    1. Create file: intent_engine/src/signals/<name>_signal.py
    2. Subclass BaseSignal, set source_name (snake_case, unique)
    3. Implement fetch() — must never raise; catch all exceptions internally
    4. Register in signals/__init__.py and pipeline.py SIGNAL_REGISTRY

KEY METHODS:
  fetch()        — MUST be implemented by every subclass; returns list of raw
                   signal dicts; should never propagate exceptions
  _make_signal() — helper to build a correctly-shaped signal dict; subclasses
                   call this for every job posting they extract

SIGNAL DICT SHAPE:
  {
    "company_name": str,   — hiring company (not the staffing agency)
    "job_title":    str,   — exact job title from the posting
    "description":  str,   — job description text (truncated to ~2000 chars)
    "url":          str,   — direct link to the job posting
    "source":       str,   — source_name attribute (e.g. "indeed", "news")
    "location":     str,   — city/country from the posting
    "posted_date":  str,   — raw date string from the posting
  }
"""

from abc import ABC, abstractmethod
from typing import Optional


class BaseSignal(ABC):
    """
    Abstract base for all oracle intent signal scrapers.

    Subclasses set source_name as a class attribute (used as the "source"
    field in the intent_signals table) and implement fetch() to scrape
    one data source for Oracle-related job postings or news articles.
    """

    source_name: str = "unknown"

    @abstractmethod
    def fetch(self, query: str, location: str = "", max_pages: int = 3) -> list[dict]:
        """
        Scrape one data source for Oracle intent signals.

        Must never raise — catch all exceptions internally and return
        whatever was collected before the error.

        Args:
            query:     Search query string (from config.ORACLE_SEARCH_QUERIES)
            location:  Geographic filter string (empty = worldwide)
            max_pages: Hard cap on pages to fetch (from config.MAX_PAGES)

        Returns:
            List of raw signal dicts, each built with _make_signal().
            Empty list if nothing found or any error occurred.
        """
        pass

    def _make_signal(
        self,
        company_name: str,
        job_title: str,
        description: str,
        url: str,
        location: str = "",
        posted_date: str = "",
        extra: Optional[dict] = None,
    ) -> dict:
        """
        Build a correctly-shaped signal dict from extracted fields.

        Strips whitespace from all string fields.
        Pass extra={} for any additional fields (e.g. salary, remote flag).

        Args:
            company_name: The HIRING company (not the staffing agency posting the job)
            job_title:    Exact title from the job post
            description:  Job description text (truncate long descriptions before passing)
            url:          Direct link to the job posting page
            location:     City, country, or "Remote" from the posting
            posted_date:  Raw date string (e.g. "2 days ago", "2024-01-15")
            extra:        Additional fields to merge into the signal dict

        Returns:
            Dict with standard keys plus any extra fields merged in.
        """
        signal = {
            "company_name": company_name.strip(),
            "job_title": job_title.strip(),
            "description": description.strip() if description else "",
            "url": url.strip(),
            "source": self.source_name,
            "location": location.strip(),
            "posted_date": posted_date.strip(),
        }
        if extra:
            signal.update(extra)
        return signal
