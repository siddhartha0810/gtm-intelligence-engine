"""
GTM agent team — narrow specialists behind one contract (see base_agent.py).

Registry pattern mirrors pipeline.py's scrapers dict: to add an agent,
subclass BaseAgent in its own file and register the instance here.
"""

from src.agents.base_agent import AgentResult, BaseAgent
from src.agents.strategist_agent import StrategistAgent
from src.agents.recalibrator_agent import RecalibratorAgent

AGENT_REGISTRY: dict[str, BaseAgent] = {
    a.name: a for a in [
        StrategistAgent(),
        RecalibratorAgent(),
    ]
}


def get_agent(name: str) -> BaseAgent | None:
    return AGENT_REGISTRY.get(name)


def list_agents() -> list[dict]:
    return [
        {"name": a.name, "description": a.description, "required_fields": a.required_fields}
        for a in AGENT_REGISTRY.values()
    ]
