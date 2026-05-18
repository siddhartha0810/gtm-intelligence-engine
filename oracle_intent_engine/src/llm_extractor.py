"""
LLM-based company name extraction via local Ollama.

Primary extractor for news/article signals — processes headlines in batches of
10 to keep scan time reasonable (one Ollama call per batch vs one per article).

Falls back gracefully to empty string when Ollama is unavailable.
"""

import re
import requests
from src.utils import get_logger, is_valid_company_name
from src import config

logger = get_logger(__name__)

_BATCH_SIZE = 10
_available_cache: bool | None = None   # None = unchecked


def is_available() -> bool:
    """Return True if Ollama is running and the configured model is loaded."""
    global _available_cache
    if _available_cache is not None:
        return _available_cache
    if not config.OLLAMA_MODEL:
        _available_cache = False
        return False
    try:
        resp = requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=3)
        models = [m["name"].split(":")[0] for m in resp.json().get("models", [])]
        model_base = config.OLLAMA_MODEL.split(":")[0]
        _available_cache = model_base in models
    except Exception:
        _available_cache = False
    return _available_cache


def extract_company(title: str, description: str = "") -> str:
    """Extract company from a single headline. Returns '' if none found."""
    results = extract_companies_batch([{"title": title, "description": description}])
    return results[0] if results else ""


def extract_companies_batch(articles: list[dict]) -> list[str]:
    """
    articles: list of {"title": str, "description": str}
    Returns a list of company names the same length as the input.
    Empty string means no company found for that article.
    """
    if not articles:
        return []
    if not is_available():
        return [""] * len(articles)

    results = []
    for i in range(0, len(articles), _BATCH_SIZE):
        chunk = articles[i : i + _BATCH_SIZE]
        results.extend(_call_ollama(chunk))
    return results


# ------------------------------------------------------------------ #
#  Internal helpers
# ------------------------------------------------------------------ #

def _call_ollama(articles: list[dict]) -> list[str]:
    """Send one batch request to Ollama and parse the numbered list response."""
    numbered = "\n".join(
        f"{i + 1}. {a.get('title', '')}"
        for i, a in enumerate(articles)
    )
    prompt = (
        "Task: for each headline, find the NON-ORACLE company that is a CUSTOMER using Oracle software.\n\n"
        "Examples:\n"
        "- 'Chipotle selects Oracle ERP' -> 1. Chipotle\n"
        "- 'Northwell Health goes live on Oracle HCM' -> 1. Northwell Health\n"
        "- 'Oracle wins deal at City of Dallas' -> 1. City of Dallas\n"
        "- 'Oracle announces new cloud features' -> 1. none\n"
        "- 'AWS launches new AI chip' -> 1. none\n\n"
        "Rules:\n"
        "- Reply ONLY as a numbered list, one line per headline\n"
        "- Format exactly: '1. CompanyName' or '1. none'\n"
        "- Never write Oracle, NetSuite, OCI, or any Oracle product name as the answer\n\n"
        "Headlines:\n" + numbered
    )
    try:
        resp = requests.post(
            f"{config.OLLAMA_URL}/api/generate",
            json={
                "model": config.OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0, "num_predict": 300},
            },
            timeout=45,
        )
        text = resp.json().get("response", "")
        return _parse_response(text, len(articles))
    except Exception as e:
        logger.debug(f"Ollama batch call failed: {e}")
        return [""] * len(articles)


def _parse_response(text: str, expected: int) -> list[str]:
    """Parse a numbered-list Ollama response into a fixed-length list of names."""
    results = [""] * expected
    for line in text.strip().splitlines():
        m = re.match(r"^\s*(\d+)[.)]\s*(.+)$", line.strip())
        if not m:
            continue
        idx = int(m.group(1)) - 1
        if not (0 <= idx < expected):
            continue
        name = m.group(2).strip().strip('"\'').rstrip(".,;")
        # Strip parenthetical suffixes added by LLM ("Acme Corp (a tech company)")
        name = re.sub(r"\s*\(.*?\)$", "", name).strip()
        if name.lower() in ("none", "n/a", "unknown", "no company", "no customer", "-", ""):
            continue
        if (
            is_valid_company_name(name)
            and "oracle" not in name.lower()
            and "netsuite" not in name.lower()
        ):
            results[idx] = name
    return results
