"""
Base class for all signal scrapers.
Each scraper returns a list of raw signal dicts with these keys:
  company_name, job_title, description, url, source, location, posted_date
"""

from abc import ABC, abstractmethod
from typing import Optional


class BaseSignal(ABC):
    source_name: str = "unknown"

    @abstractmethod
    def fetch(self, query: str, location: str = "", max_pages: int = 3) -> list[dict]:
        """Return list of raw signal dicts."""
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
