"""Google ADK agent definitions for the production milestone.

Install the optional dependencies with `pip install -e ".[google]"`.
Business mutations must be wired to the validated operations in
`app.workflow.WorkflowEngine`; never give the model direct database access.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent

from app.agent_tools import build_toolsets
from app.agents.specialist import DeterministicSpecialistAgent
from app.config import settings
from app.registry import RegistryAgentResolver
from app.runtime_state import engine as _engine
from app.telemetry import after_model_call, model_budget_callback

_recall_tools, _supply_tools, _finance_tools = build_toolsets(_engine)
_before_model_call = model_budget_callback(settings.max_model_calls)

supply_agent = DeterministicSpecialistAgent(
    name="supply_continuity",
    description="Restores supply using compliant suppliers and bounded purchase authority.",
    handler=_supply_tools.restore_supply,
)

finance_agent = DeterministicSpecialistAgent(
    name="financial_recovery",
    description="Calculates recall losses, holds linked invoices, and creates supplier claims.",
    handler=_finance_tools.recover_finances,
)

registered_specialists: dict[str, object] = {}
if settings.agent_runtime_mode == "adk" and settings.agent_role == "recall":
    _resolver = RegistryAgentResolver(
        settings.google_cloud_project,
        settings.agent_registry_location,
    )
    _supply_remote, _finance_remote = _resolver.resolve_specialists(
        settings.supply_agent_resource,
        settings.finance_agent_resource,
    )
    registered_specialists = {"supply": _supply_remote, "finance": _finance_remote}

recall_agent = LlmAgent(
    name="recall_coordinator",
    model=settings.routine_model,
    description="Contains product recalls and coordinates downstream recovery.",
    instruction=(
        "Match products and lots conservatively. Use deterministic tools for every mutation. "
        "Freeze exact matches immediately and request approval for ambiguity. Process inventory "
        "receipt and transfer events with their matching typed tools. After calling a typed tool, "
        "summarize its result; the bounded runtime performs Registry-resolved specialist handoffs "
        "from the deterministic routing flags. Never invent an agent URL."
    ),
    tools=[
        _recall_tools.contain_recall,
        _recall_tools.receive_inventory,
        _recall_tools.transfer_inventory,
    ],
    before_model_callback=_before_model_call,
    after_model_callback=after_model_call,
)

root_agent = {
    "recall": recall_agent,
    "supply": supply_agent,
    "finance": finance_agent,
}[settings.agent_role]
