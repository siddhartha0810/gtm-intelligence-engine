"""
base_agent.py
=============
Contract every GTM agent must honour — the reason the agent team runs
"without breakers".

An agent is a narrow specialist with:
  - a unique name (snake_case, used in the registry and API routes)
  - required_fields it validates before doing anything
  - an _execute() that does one job and returns a dict

run() is the only public entry point and it NEVER raises: validation
errors, LLM failures, and bugs inside _execute() all come back as a
structured AgentResult with ok=False. Agents also self-report `degraded`
when they completed via a fallback path (e.g. no LLM available), so the
orchestrator and UI can distinguish "best answer" from "backup answer".

Agents never call each other. They read a payload, do their job, return a
result — collaboration happens through the database / pipeline that chains
them, not through agent-to-agent chatter.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from src.utils import get_logger

logger = get_logger(__name__)


@dataclass
class AgentResult:
    agent: str
    ok: bool
    data: dict = field(default_factory=dict)
    error: str | None = None
    degraded: bool = False          # completed via fallback (e.g. no LLM)
    duration_ms: int = 0

    def as_dict(self) -> dict:
        return {
            "agent":       self.agent,
            "ok":          self.ok,
            "data":        self.data,
            "error":       self.error,
            "degraded":    self.degraded,
            "duration_ms": self.duration_ms,
        }


class BaseAgent(ABC):
    """Subclasses set name/description/required_fields and implement _execute()."""

    name: str = "unknown"
    description: str = ""
    required_fields: list[str] = []

    def run(self, payload: dict) -> AgentResult:
        """Validate → execute → wrap. Never raises."""
        start = time.time()

        missing = [f for f in self.required_fields
                   if not str(payload.get(f, "") or "").strip()]
        if missing:
            return AgentResult(
                agent=self.name, ok=False,
                error=f"missing required field(s): {', '.join(missing)}",
            )

        try:
            data = self._execute(payload) or {}
            degraded = bool(data.pop("_degraded", False))
            result = AgentResult(agent=self.name, ok=True, data=data, degraded=degraded)
        except Exception as e:
            logger.error("[%s] agent failed: %s", self.name, e, exc_info=True)
            result = AgentResult(agent=self.name, ok=False, error=str(e))

        result.duration_ms = int((time.time() - start) * 1000)
        logger.info("[%s] ok=%s degraded=%s in %dms",
                    self.name, result.ok, result.degraded, result.duration_ms)
        return result

    @abstractmethod
    def _execute(self, payload: dict) -> dict:
        """Do the agent's one job. May raise — run() catches everything.
        Set "_degraded": True in the returned dict when a fallback path
        produced the answer."""
        ...
