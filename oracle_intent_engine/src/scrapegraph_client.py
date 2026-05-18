"""
ScrapeGraphAI integration.

Setup:
  pip install scrapegraphai
  playwright install chromium

Configure in .env:
  # Free / local (needs Ollama running + models pulled):
  SCRAPEGRAPH_MODEL=ollama/llama3.1
  # Also pull the embeddings model:  ollama pull nomic-embed-text

  # Paid / higher quality (recommended):
  SCRAPEGRAPH_MODEL=anthropic/claude-haiku-4-5-20251001
  SCRAPEGRAPH_API_KEY=sk-ant-...

If SCRAPEGRAPH_MODEL is empty, all functions are no-ops and callers fall back
to their existing logic — nothing breaks if the library is not installed.
"""

import json
from src.utils import get_logger
from src import config

logger = get_logger(__name__)

_sgai_available = False

try:
    from scrapegraphai.graphs import SmartScraperGraph
    _sgai_available = True
except ImportError:
    logger.info("scrapegraphai not installed — LLM scraping disabled. "
                "Run: pip install scrapegraphai && playwright install chromium")


def is_available() -> bool:
    return _sgai_available and bool(config.SCRAPEGRAPH_MODEL)


def _graph_config(headless: bool = True) -> dict:
    model = config.SCRAPEGRAPH_MODEL
    llm = {"model": model, "temperature": 0}

    if config.SCRAPEGRAPH_API_KEY:
        llm["api_key"] = config.SCRAPEGRAPH_API_KEY

    cfg = {"llm": llm, "verbose": False, "headless": headless}

    if model.startswith("ollama/"):
        llm["base_url"] = config.SCRAPEGRAPH_OLLAMA_URL
        cfg["embeddings"] = {
            "model": "ollama/nomic-embed-text",
            "base_url": config.SCRAPEGRAPH_OLLAMA_URL,
        }

    return cfg


def scrape_page(url: str, prompt: str) -> dict | list | None:
    """
    Scrape a URL using a headless browser + LLM extraction.
    Returns structured data (dict or list) or None on failure.
    """
    if not is_available():
        return None
    try:
        graph = SmartScraperGraph(
            prompt=prompt,
            source=url,
            config=_graph_config(headless=True),
        )
        result = graph.run()
        logger.info(f"ScrapeGraphAI scraped: {url}")
        return result
    except Exception as e:
        logger.warning(f"ScrapeGraphAI scrape_page failed ({url}): {e}")
        return None


def extract_entities(text: str, prompt: str) -> dict | None:
    """
    Run LLM inference on plain text — no HTTP fetch, no browser.
    Uses litellm (bundled with scrapegraphai) for a direct, lightweight call.
    Returns a parsed dict or None.
    """
    if not is_available():
        return None
    try:
        import litellm

        model = config.SCRAPEGRAPH_MODEL
        kwargs: dict = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"{prompt}\n\n"
                        f"Text:\n{text}\n\n"
                        "Respond with valid JSON only. No explanation."
                    ),
                }
            ],
            "temperature": 0,
        }
        if config.SCRAPEGRAPH_API_KEY:
            kwargs["api_key"] = config.SCRAPEGRAPH_API_KEY
        if model.startswith("ollama/"):
            kwargs["api_base"] = config.SCRAPEGRAPH_OLLAMA_URL

        response = litellm.completion(**kwargs)
        raw = response.choices[0].message.content or ""

        # Strip markdown code fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        return json.loads(raw)
    except json.JSONDecodeError:
        return None
    except Exception as e:
        logger.warning(f"ScrapeGraphAI extract_entities failed: {e}")
        return None
