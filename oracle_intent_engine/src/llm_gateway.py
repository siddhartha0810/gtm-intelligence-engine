"""
llm_gateway.py
==============
Single LLM entry point for every GTM agent — provider-agnostic, never raises.

PURPOSE:
  All agents (strategist, classifier, copywriter, ...) call the gateway
  instead of instantiating their own LLM clients. The gateway tries local
  Ollama first ($0, same instance llm_extractor.py already uses), falls back
  to Anthropic if ANTHROPIC_API_KEY is set, and returns "" when neither is
  available — callers degrade gracefully instead of crashing ("no breakers").

MODEL ROUTING:
  task="extract" | "classify"  → small local model (fast, cheap)
  task="reason"  | "copy"      → larger local model if OLLAMA_MODEL_LARGE is
                                 set, else the default; Anthropic Haiku on
                                 fallback either way.

USAGE:
    from src import llm_gateway
    text = llm_gateway.complete("Summarise this...", task="reason")
    data = llm_gateway.complete_json(prompt, system="Reply as JSON only.")
"""

from __future__ import annotations

import json
import os
import re
import time

import requests

from src.utils import get_logger
from src import config

logger = get_logger(__name__)

_OLLAMA_TIMEOUT = 60
_RETRIES_PER_PROVIDER = 2
_RETRY_BACKOFF_SECONDS = 1.5

_ANTHROPIC_MODEL = os.getenv("LLM_GATEWAY_ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
_OLLAMA_MODEL_LARGE = os.getenv("OLLAMA_MODEL_LARGE", "").strip()

_SMALL_TASKS = ("extract", "classify")

_ollama_available: bool | None = None  # None = unchecked, cached per process


def _ollama_model_for(task: str) -> str:
    if task not in _SMALL_TASKS and _OLLAMA_MODEL_LARGE:
        return _OLLAMA_MODEL_LARGE
    return config.OLLAMA_MODEL


def ollama_available() -> bool:
    """True if Ollama is running and the configured model is pulled. Cached."""
    global _ollama_available
    if _ollama_available is not None:
        return _ollama_available
    if not config.OLLAMA_MODEL:
        _ollama_available = False
        return False
    try:
        resp = requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=3)
        models = [m["name"].split(":")[0] for m in resp.json().get("models", [])]
        _ollama_available = config.OLLAMA_MODEL.split(":")[0] in models
    except Exception:
        _ollama_available = False
    if not _ollama_available:
        logger.info("[LLMGateway] Ollama unavailable at %s", config.OLLAMA_URL)
    return _ollama_available


def anthropic_available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY", "").strip())


def is_available() -> bool:
    return ollama_available() or anthropic_available()


def _call_ollama(prompt: str, system: str, task: str, max_tokens: int) -> str:
    resp = requests.post(
        f"{config.OLLAMA_URL}/api/generate",
        json={
            "model": _ollama_model_for(task),
            "prompt": prompt,
            "system": system or "",
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": max_tokens},
        },
        timeout=_OLLAMA_TIMEOUT,
    )
    resp.raise_for_status()
    return (resp.json().get("response") or "").strip()


def _call_anthropic(prompt: str, system: str, max_tokens: int) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", "").strip())
    kwargs = {
        "model": _ANTHROPIC_MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system
    message = client.messages.create(**kwargs)
    return message.content[0].text.strip()


def complete(prompt: str, system: str = "", task: str = "reason",
             max_tokens: int = 800) -> str:
    """
    Run one completion through the best available provider.
    Returns "" if every provider fails — never raises.
    """
    providers = []
    if ollama_available():
        providers.append(("ollama", lambda: _call_ollama(prompt, system, task, max_tokens)))
    if anthropic_available():
        providers.append(("anthropic", lambda: _call_anthropic(prompt, system, max_tokens)))

    for name, call in providers:
        for attempt in range(1, _RETRIES_PER_PROVIDER + 1):
            try:
                result = call()
                if result:
                    return result
            except Exception as e:
                logger.debug("[LLMGateway] %s attempt %d failed: %s", name, attempt, e)
                if attempt < _RETRIES_PER_PROVIDER:
                    time.sleep(_RETRY_BACKOFF_SECONDS * attempt)
        logger.warning("[LLMGateway] provider %s exhausted retries — trying next", name)

    if not providers:
        logger.info("[LLMGateway] no LLM provider available (Ollama down, no ANTHROPIC_API_KEY)")
    return ""


def _extract_json_block(raw: str) -> str:
    """Pull a JSON object out of a possibly-fenced / chatty LLM response."""
    if "```" in raw:
        for chunk in raw.split("```"):
            chunk = chunk.strip()
            if chunk.startswith("json"):
                chunk = chunk[4:].strip()
            if chunk.startswith("{"):
                return chunk
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    return match.group(0) if match else raw


def complete_json(prompt: str, system: str = "", task: str = "reason",
                  max_tokens: int = 800) -> dict | None:
    """
    complete() + robust JSON parsing. Returns None if the model produced
    nothing parseable — callers must handle None (their degraded path).
    """
    raw = complete(prompt, system=system, task=task, max_tokens=max_tokens)
    if not raw:
        return None
    try:
        parsed = json.loads(_extract_json_block(raw))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        logger.debug("[LLMGateway] unparseable JSON response: %.200s", raw)
        return None
