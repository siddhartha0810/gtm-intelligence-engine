"""
llm_gateway.py  (v2)
====================
Single LLM entry point for every GTM agent — provider-agnostic, never raises.

PROVIDERS (tried in order, only if configured/reachable):
  1. Groq       — free tier, OpenAI-compatible, very fast (Llama 3.3 70B)
  2. Gemini     — free tier, OpenAI-compatible, huge context (2.5 Flash)
  3. Ollama     — local, unlimited, private (same instance llm_extractor uses)
  4. Anthropic  — quality ceiling (Haiku) via SDK
Order overridable with LLM_PROVIDER_ORDER="groq,gemini,ollama,anthropic".

MODEL ROUTING:
  task="extract" | "classify"  → fast model tier
  task="reason"  | "copy"      → smart model tier

COST/RELIABILITY FEATURES (v2):
  * SQLite response cache — identical (system, prompt, tier) re-runs cost 0 calls
  * Per-run budget cap — hard ceiling on provider calls; over budget → returns ""
    (never silently overspends, never raises). reset_budget() at each run start.
  * Mock mode (LLM_MOCK=1) — deterministic canned answers, no keys, no network,
    so the whole pipeline is testable offline.

Never raises: every provider failure, budget stop, and parse error returns
"" / None so callers degrade gracefully ("no breakers").

USAGE:
    from src import llm_gateway
    llm_gateway.reset_budget(300)              # at run start (optional)
    text = llm_gateway.complete("Summarise…", task="reason")
    data = llm_gateway.complete_json(prompt, system="Reply as JSON only.")
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time

import requests

from src.utils import get_logger
from src import config

logger = get_logger(__name__)

_HTTP_TIMEOUT = 60
_RETRIES_PER_PROVIDER = 2
_RETRY_BACKOFF_SECONDS = 1.5

# ── Provider registry ─────────────────────────────────────────────────────────
# OpenAI-compatible providers share one chat() path; Ollama + Anthropic have
# their own. models: {"smart": ..., "fast": ...}
_OPENAI_PROVIDERS = {
    "groq": {
        "base": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "models": {"smart": os.getenv("GROQ_MODEL_SMART", "llama-3.3-70b-versatile"),
                   "fast":  os.getenv("GROQ_MODEL_FAST",  "llama-3.1-8b-instant")},
    },
    "gemini": {
        "base": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_env": "GEMINI_API_KEY",
        "models": {"smart": os.getenv("GEMINI_MODEL_SMART", "gemini-2.5-flash"),
                   "fast":  os.getenv("GEMINI_MODEL_FAST",  "gemini-2.5-flash-lite")},
    },
}

_ANTHROPIC_MODEL = os.getenv("LLM_GATEWAY_ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
_OLLAMA_MODEL_LARGE = os.getenv("OLLAMA_MODEL_LARGE", "").strip()

_SMALL_TASKS = ("extract", "classify")

_DEFAULT_ORDER = ["groq", "gemini", "ollama", "anthropic"]


def _provider_order() -> list[str]:
    env = os.getenv("LLM_PROVIDER_ORDER", "").strip()
    if env:
        return [p.strip() for p in env.split(",") if p.strip()]
    return list(_DEFAULT_ORDER)


def _tier_for(task: str) -> str:
    return "fast" if task in _SMALL_TASKS else "smart"


# ── Availability (cached per process) ────────────────────────────────────────
_ollama_available: bool | None = None


def _openai_provider_ready(name: str) -> bool:
    p = _OPENAI_PROVIDERS.get(name)
    return bool(p) and bool(os.getenv(p["key_env"], "").strip())


def ollama_available() -> bool:
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
    return _ollama_available


def anthropic_available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY", "").strip())


def _provider_available(name: str) -> bool:
    if name in _OPENAI_PROVIDERS:
        return _openai_provider_ready(name)
    if name == "ollama":
        return ollama_available()
    if name == "anthropic":
        return anthropic_available()
    return False


def is_available() -> bool:
    if _mock_enabled():
        return True
    return any(_provider_available(p) for p in _provider_order())


def active_providers() -> list[str]:
    """Which providers are actually usable right now — for /api diagnostics."""
    return [p for p in _provider_order() if _provider_available(p)]


# ── Mock mode ─────────────────────────────────────────────────────────────────
def _mock_enabled() -> bool:
    return os.getenv("LLM_MOCK", "").strip().lower() in ("1", "true", "yes")


def _mock_response(prompt: str, system: str) -> str:
    """Deterministic canned answer for offline pipeline tests. If the caller
    asked for JSON (via system prompt), return a minimal valid JSON object."""
    wants_json = "json" in (system or "").lower() or "json" in prompt.lower()[:200]
    if wants_json:
        return json.dumps({"mock": True, "note": "LLM_MOCK enabled — no real call made"})
    return "[MOCK] llm_gateway mock response (LLM_MOCK enabled)"


# ── Budget meter ──────────────────────────────────────────────────────────────
_budget_lock = threading.Lock()
_call_count = 0
_budget_ceiling = int(os.getenv("LLM_MAX_CALLS_PER_RUN", "500"))


def reset_budget(ceiling: int | None = None) -> None:
    """Call at the start of a scan/agent run. Resets the call counter and,
    optionally, the ceiling for this run."""
    global _call_count, _budget_ceiling
    with _budget_lock:
        _call_count = 0
        if ceiling is not None:
            _budget_ceiling = int(ceiling)


def get_budget_status() -> dict:
    with _budget_lock:
        return {"used": _call_count, "ceiling": _budget_ceiling,
                "remaining": max(0, _budget_ceiling - _call_count)}


def _budget_ok_and_increment() -> bool:
    global _call_count
    with _budget_lock:
        if _call_count >= _budget_ceiling:
            return False
        _call_count += 1
        return True


# ── Response cache (SQLite) ───────────────────────────────────────────────────
_cache_conn: sqlite3.Connection | None = None
_cache_lock = threading.Lock()


def _cache() -> sqlite3.Connection | None:
    global _cache_conn
    if _cache_conn is not None:
        return _cache_conn
    try:
        path = os.getenv("LLM_CACHE_PATH", os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "llm_cache.db"))
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.execute("CREATE TABLE IF NOT EXISTS llm_cache "
                     "(k TEXT PRIMARY KEY, v TEXT, created_at REAL)")
        conn.commit()
        _cache_conn = conn
    except Exception as e:
        logger.debug("[LLMGateway] cache unavailable: %s", e)
        _cache_conn = None
    return _cache_conn


def _cache_key(tier: str, system: str, prompt: str) -> str:
    return hashlib.sha256(f"{tier}|{system}|{prompt}".encode()).hexdigest()


def _cache_get(key: str) -> str | None:
    conn = _cache()
    if conn is None:
        return None
    with _cache_lock:
        row = conn.execute("SELECT v FROM llm_cache WHERE k=?", (key,)).fetchone()
    return row[0] if row else None


def _cache_put(key: str, value: str) -> None:
    conn = _cache()
    if conn is None or not value:
        return
    try:
        with _cache_lock:
            conn.execute("INSERT OR REPLACE INTO llm_cache VALUES (?,?,?)",
                         (key, value, time.time()))
            conn.commit()
    except Exception:
        pass


# ── Provider call paths ───────────────────────────────────────────────────────
def _call_openai_compatible(name: str, tier: str, system: str, user: str,
                            max_tokens: int) -> str:
    p = _OPENAI_PROVIDERS[name]
    key = os.getenv(p["key_env"], "").strip()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    resp = requests.post(
        f"{p['base']}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": p["models"][tier], "messages": messages,
              "temperature": 0.2, "max_tokens": max_tokens},
        timeout=_HTTP_TIMEOUT,
    )
    if resp.status_code == 429:
        raise RuntimeError(f"{name} rate-limited (429)")
    resp.raise_for_status()
    return (resp.json()["choices"][0]["message"]["content"] or "").strip()


def _call_ollama(tier: str, system: str, user: str, max_tokens: int) -> str:
    model = _OLLAMA_MODEL_LARGE if (tier == "smart" and _OLLAMA_MODEL_LARGE) else config.OLLAMA_MODEL
    resp = requests.post(
        f"{config.OLLAMA_URL}/api/generate",
        json={"model": model, "prompt": user, "system": system or "",
              "stream": False, "options": {"temperature": 0.2, "num_predict": max_tokens}},
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return (resp.json().get("response") or "").strip()


def _call_anthropic(system: str, user: str, max_tokens: int) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", "").strip())
    kwargs = {"model": _ANTHROPIC_MODEL, "max_tokens": max_tokens,
              "messages": [{"role": "user", "content": user}]}
    if system:
        kwargs["system"] = system
    msg = client.messages.create(**kwargs)
    return msg.content[0].text.strip()


def _dispatch(name: str, tier: str, system: str, user: str, max_tokens: int) -> str:
    if name in _OPENAI_PROVIDERS:
        return _call_openai_compatible(name, tier, system, user, max_tokens)
    if name == "ollama":
        return _call_ollama(tier, system, user, max_tokens)
    if name == "anthropic":
        return _call_anthropic(system, user, max_tokens)
    return ""


# ── Public API ────────────────────────────────────────────────────────────────
def complete(prompt: str, system: str = "", task: str = "reason",
             max_tokens: int = 800, no_cache: bool = False) -> str:
    """
    One completion via the best available provider. Cache hit → free.
    Budget exhausted or every provider fails → "" (never raises).
    """
    if _mock_enabled():
        return _mock_response(prompt, system)

    tier = _tier_for(task)
    key = _cache_key(tier, system, prompt)
    if not no_cache:
        cached = _cache_get(key)
        if cached is not None:
            return cached

    providers = [p for p in _provider_order() if _provider_available(p)]
    if not providers:
        logger.info("[LLMGateway] no provider available (set GROQ/GEMINI/ANTHROPIC key or run Ollama)")
        return ""

    for name in providers:
        if not _budget_ok_and_increment():
            logger.warning("[LLMGateway] per-run call budget (%d) exhausted — stopping",
                           _budget_ceiling)
            return ""
        for attempt in range(1, _RETRIES_PER_PROVIDER + 1):
            try:
                result = _dispatch(name, tier, system, prompt, max_tokens)
                if result:
                    if not no_cache:
                        _cache_put(key, result)
                    return result
                break  # empty but no error — try next provider
            except Exception as e:
                logger.debug("[LLMGateway] %s attempt %d failed: %s", name, attempt, e)
                if attempt < _RETRIES_PER_PROVIDER:
                    time.sleep(_RETRY_BACKOFF_SECONDS * attempt)
        logger.warning("[LLMGateway] provider %s exhausted — trying next", name)

    return ""


def _extract_json_block(raw: str) -> str:
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
                  max_tokens: int = 800, no_cache: bool = False) -> dict | None:
    """complete() + robust JSON parsing. None if nothing parseable (caller's
    degraded path)."""
    raw = complete(prompt, system=system, task=task, max_tokens=max_tokens, no_cache=no_cache)
    if not raw:
        return None
    try:
        parsed = json.loads(_extract_json_block(raw))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        logger.debug("[LLMGateway] unparseable JSON response: %.200s", raw)
        return None
