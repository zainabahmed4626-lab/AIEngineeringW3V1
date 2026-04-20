"""
High-level scenario tests: billing (MCP tool functions), returns (A2A agent), escalation.

Uses mocks so no live Supabase, Gemini, or returns microservice is required.
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)

from src.agents.billing_agent import BillingAgent  # noqa: E402
from src.agents.router_agent import RouterAgent, RouterDecision  # noqa: E402
from src.agents.support_agent import SupportAgent  # noqa: E402
from src.agents.returns_remote_agent import ReturnsRemoteAgent  # noqa: E402


def _make_router(
    *,
    billing: BillingAgent | None = None,
    support: SupportAgent | None = None,
    returns: ReturnsRemoteAgent | None = None,
) -> RouterAgent:
    return RouterAgent(
        billing=billing or BillingAgent(),
        support=support or SupportAgent(),
        returns=returns or ReturnsRemoteAgent("http://127.0.0.1:8081"),
    )


@pytest.mark.asyncio
async def test_billing_scenario_mcp_tools_used() -> None:
    """
    User asks about duplicate charges; router -> BillingAgent; offline path calls
    ``get_billing_info`` / ``get_support_tickets`` (same functions as the Supabase MCP server).
    """
    query = "I was charged twice for my last order. Can you check my billing?"
    customer_id = "billing-scenario@example.com"

    billing_payload = {
        "customer": {
            "id": "c1",
            "name": "Scenario User",
            "email": customer_id,
        },
        "orders": [
            {
                "order_number": "ORD-1001",
                "total_amount": 49.99,
                "status": "paid",
            }
        ],
        "order_count": 1,
    }
    tickets_payload = {"tickets": [], "ticket_count": 0}

    with (
        patch("src.agents.billing_agent.genai_api_configured", return_value=False),
        patch(
            "src.agents.billing_agent.get_billing_info",
            return_value=json.dumps(billing_payload),
        ) as mock_billing,
        patch(
            "src.agents.billing_agent.get_support_tickets",
            return_value=json.dumps(tickets_payload),
        ) as mock_tickets,
    ):
        router = _make_router()
        out = await router.route_with_meta(customer_id, query)

    assert out.routed_to == "billing"
    assert out.escalated is False
    mock_billing.assert_called_once()
    mock_tickets.assert_called_once()
    # Billing explanation from offline formatter
    assert "billing" in out.answer.lower() or "BillingAgent" in out.answer
    assert "ORD-1001" in out.answer or "order" in out.answer.lower()


@pytest.mark.asyncio
async def test_returns_scenario_eligibility_path() -> None:
    """
    Returns query -> router picks returns; ``ReturnsRemoteAgent.check_return_eligibility``
    is exercised with A2A stack mocked.
    """
    query = "I want to return order 123456. Am I eligible?"
    customer_id = "returns-user@example.com"

    returns = ReturnsRemoteAgent("http://127.0.0.1:8081")
    router = _make_router(returns=returns)

    with patch.object(returns, "handle", new_callable=AsyncMock) as mock_handle:
        mock_handle.return_value = (
            "For order 123456, eligibility: yes — your order qualifies for a return."
        )
        routed = await router.route_with_meta(customer_id, query)

    assert routed.routed_to == "returns"
    assert routed.escalated is False
    mock_handle.assert_called_once_with(customer_id, query)
    assert "eligible" in routed.answer.lower() or "qualif" in routed.answer.lower()

    with patch(
        "src.agents.returns_remote_agent.run_llm_agent_once",
        new_callable=AsyncMock,
    ) as mock_run:
        mock_run.return_value = '{"eligible": true, "reason": "last digit even"}'
        result = await returns.check_return_eligibility("123456")
    mock_run.assert_awaited()
    assert result.get("eligible") is True
    assert "reason" in result


@pytest.mark.asyncio
async def test_escalation_scenario_flag() -> None:
    """
    Security-sensitive message -> router escalates; metadata maps to ``escalated`` on
    :class:`~src.agents.router_agent.RouterOutcome` (HTTP API uses ``escalated`` / ``routed_to``).
    """
    query = (
        "My account was hacked and all my orders disappeared "
        "and support is ignoring me."
    )
    decision = RouterDecision(
        route="support",
        escalate=True,
        rationale="account security / suspected compromise",
    )

    with (
        patch("src.agents.router_agent.genai_api_configured", return_value=True),
        patch(
            "src.agents.router_agent.run_router_structured",
            new_callable=AsyncMock,
            return_value=decision,
        ),
    ):
        router = _make_router()
        out = await router.route_with_meta("cust-1", query)

    assert out.escalated is True
    assert out.routed_to == "escalate"
    assert "[ESCALATE]" in out.answer
    # Example metadata shape consumers may mirror
    metadata = {"escalate": out.escalated, "routed_to": out.routed_to}
    assert metadata["escalate"] is True
