"""A2A wrapper for the full customer support system (router + specialists + loop).

This module wires the same specialist graph used by `src.main`, but exposes it as an
Agent-to-Agent (A2A) callable agent instead of an interactive CLI/API entrypoint.
"""

from __future__ import annotations

import os
from typing import Any

from google.adk.agents.llm_agent import LlmAgent
from google.adk.a2a.utils.agent_to_a2a import to_a2a as adk_to_a2a
from google.adk.tools.function_tool import FunctionTool

from src.agents.billing_agent import BillingAgent
from src.agents.loop_agent import LoopAgent
from src.agents.router_agent import RouterAgent
from src.agents.returns_remote_agent import ReturnsRemoteAgent
from src.agents.support_agent import SupportAgent

RETURNS_SERVICE_URL = os.getenv("RETURNS_SERVICE_URL", "http://127.0.0.1:8081")
DEFAULT_CUSTOMER_ID = os.getenv("SUPPORT_SYSTEM_DEFAULT_CUSTOMER_ID", "demo@example.com")

# This wiring intentionally mirrors src.main so behavior stays aligned across entrypoints.
billing_agent = BillingAgent()
support_agent = SupportAgent()
returns_remote_agent = ReturnsRemoteAgent(RETURNS_SERVICE_URL)
loop_agent = LoopAgent()
router_agent = RouterAgent(
    billing=billing_agent,
    support=support_agent,
    returns=returns_remote_agent,
)


async def handle_support_query(query: str) -> dict[str, Any]:
    """Route a support query, refine the answer with LoopAgent, and return structured JSON.

    This is the single high-level tool exposed over A2A so external services can call one API
    instead of orchestrating specialists themselves.
    """
    raw_outcome = await router_agent.route_with_meta(DEFAULT_CUSTOMER_ID, query)
    review_context = {
        "routed_to": raw_outcome.routed_to,
        "metadata": {
            "escalate": raw_outcome.escalated,
            "rationale": raw_outcome.rationale,
        },
    }
    reviewed = loop_agent.process(query=query, raw_answer=raw_outcome.answer, context=review_context)
    return {
        "final_answer": reviewed["final_answer"],
        "review_notes": reviewed["review_notes"],
        "routed_to": raw_outcome.routed_to,
        "escalate": raw_outcome.escalated,
        "rationale": raw_outcome.rationale,
        "customer_id": DEFAULT_CUSTOMER_ID,
    }


_SUPPORT_SYSTEM_A2A_INSTRUCTION = """You are the external interface to the customer support system.

Always call the tool `handle_support_query` exactly once with the user's full message as `query`.
Return a concise answer using `final_answer` and keep routing metadata available when useful.
"""


def build_support_system_llm_agent() -> LlmAgent:
    """Build the A2A-exposed ADK agent with one orchestration tool."""
    model = os.getenv("ADK_MODEL", "gemini-2.5-flash")
    return LlmAgent(
        name="support_system_agent",
        model=model,
        description="Routes support queries to billing/support/returns specialists and refines output.",
        instruction=_SUPPORT_SYSTEM_A2A_INSTRUCTION,
        tools=[FunctionTool(handle_support_query)],
    )


def to_a2a(host: str = "127.0.0.1", port: int = 8082) -> Any:
    """Return the ASGI A2A app descriptor for the full support system."""
    agent = build_support_system_llm_agent()
    return adk_to_a2a(agent, host=host, port=port, protocol="http")

