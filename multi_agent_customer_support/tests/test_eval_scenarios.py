"""Eval-style end-to-end routing scenarios with mocked MCP/A2A dependencies."""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)

from src.agents.billing_agent import BillingAgent  # noqa: E402
from src.agents.loop_agent import LoopAgent  # noqa: E402
from src.agents.router_agent import RouterAgent, RouterDecision  # noqa: E402
from src.agents.support_agent import SupportAgent  # noqa: E402
from src.agents.returns_remote_agent import ReturnsRemoteAgent  # noqa: E402


class _StubSpecialist:
    """Tiny stub with async handle for RouterAgent dependencies."""

    def __init__(self, answer: str) -> None:
        self.handle = AsyncMock(return_value=answer)


def _looped_answer(query: str, raw_answer: str, routed_to: str, escalated: bool) -> tuple[str, list[str]]:
    """Apply LoopAgent using a metadata context shape used by the app."""
    reviewed = LoopAgent().process(
        query=query,
        raw_answer=raw_answer,
        context={"routed_to": routed_to, "metadata": {"escalate": escalated}},
    )
    return str(reviewed["final_answer"]), list(reviewed["review_notes"])


@pytest.mark.asyncio
async def test_eval_billing_double_charge_routes_mcp_and_loop() -> None:
    query = "I was charged twice for my last order, can you check?"
    customer_id = "billing-user@example.com"

    tools_called: list[str] = []

    def _fake_tool_call(tool_name: str, email: str) -> str:
        tools_called.append(tool_name)
        if tool_name == "get_billing_info":
            return json.dumps(
                {
                    "customer": {"id": "c1", "name": "Billing User", "email": email},
                    "orders": [{"order_number": "ORD-7777", "total_amount": 59.0, "status": "paid"}],
                    "order_count": 1,
                }
            )
        if tool_name == "get_support_tickets":
            return json.dumps({"tickets": [], "ticket_count": 0})
        raise AssertionError(f"Unexpected tool call: {tool_name}")

    with (
        patch("src.agents.router_agent.genai_api_configured", return_value=False),
        patch("src.agents.billing_agent.genai_api_configured", return_value=False),
        patch("src.agents.billing_agent.resolve_customer_email", return_value=customer_id),
        patch("src.agents.billing_agent._call_allowed_tool", side_effect=_fake_tool_call),
    ):
        router = RouterAgent(
            billing=BillingAgent(),
            support=_StubSpecialist("support fallback answer"),
            returns=_StubSpecialist("returns fallback answer"),
        )
        out = await router.route_with_meta(customer_id, query)

    final_answer, review_notes = _looped_answer(query, out.answer, out.routed_to, out.escalated)

    assert out.routed_to == "billing"
    assert out.escalated is False
    assert "get_billing_info" in tools_called
    assert "clear" in " ".join(review_notes).lower() or len(final_answer) < 650
    assert "order" in final_answer.lower() or "charge" in final_answer.lower()


@pytest.mark.asyncio
async def test_eval_returns_eligibility_routes_and_calls_check() -> None:
    query = "Can I return order 123456?"
    customer_id = "returns-user@example.com"

    returns = ReturnsRemoteAgent("http://127.0.0.1:8081")
    returns.check_return_eligibility = AsyncMock(
        return_value={"eligible": True, "reason": "within return window"}
    )
    returns.initiate_return = AsyncMock()

    async def _fake_handle(_: str, message: str) -> str:
        result = await returns.check_return_eligibility("123456")
        return f"Order 123456 eligibility: {'eligible' if result['eligible'] else 'not eligible'}."

    returns.handle = AsyncMock(side_effect=_fake_handle)

    with patch("src.agents.router_agent.genai_api_configured", return_value=False):
        router = RouterAgent(
            billing=_StubSpecialist("billing answer"),
            support=_StubSpecialist("support answer"),
            returns=returns,
        )
        out = await router.route_with_meta(customer_id, query)

    final_answer, _ = _looped_answer(query, out.answer, out.routed_to, out.escalated)

    assert out.routed_to == "returns"
    assert out.escalated is False
    returns.check_return_eligibility.assert_awaited_once()
    assert "eligib" in final_answer.lower()


@pytest.mark.asyncio
async def test_eval_returns_initiate_routes_and_calls_initiate() -> None:
    query = "Please start a return for order 987654 because it arrived damaged."
    customer_id = "returns-user@example.com"

    returns = ReturnsRemoteAgent("http://127.0.0.1:8081")
    returns.check_return_eligibility = AsyncMock()
    returns.initiate_return = AsyncMock(
        return_value={"return_id": "RET-9001", "status": "initiated", "message": "Return started."}
    )

    async def _fake_handle(_: str, message: str) -> str:
        result = await returns.initiate_return("987654", message)
        return f"{result['message']} return_id={result['return_id']} status={result['status']}"

    returns.handle = AsyncMock(side_effect=_fake_handle)

    with patch("src.agents.router_agent.genai_api_configured", return_value=False):
        router = RouterAgent(
            billing=_StubSpecialist("billing answer"),
            support=_StubSpecialist("support answer"),
            returns=returns,
        )
        out = await router.route_with_meta(customer_id, query)

    final_answer, _ = _looped_answer(query, out.answer, out.routed_to, out.escalated)

    assert out.routed_to == "returns"
    assert out.escalated is False
    returns.initiate_return.assert_awaited_once()
    assert "return_id=" in final_answer.lower()
    assert "status=" in final_answer.lower()


@pytest.mark.asyncio
async def test_eval_escalation_sets_metadata_and_keeps_user_facing_text() -> None:
    query = "My account was hacked and all my orders are gone and no one is responding."
    decision = RouterDecision(
        route="support",
        escalate=True,
        rationale="suspected account compromise",
    )

    with (
        patch("src.agents.router_agent.genai_api_configured", return_value=True),
        patch(
            "src.agents.router_agent.run_router_structured",
            new_callable=AsyncMock,
            return_value=decision,
        ),
    ):
        router = RouterAgent(
            billing=_StubSpecialist("billing answer"),
            support=SupportAgent(),
            returns=_StubSpecialist("returns answer"),
        )
        out = await router.route_with_meta("cust-1", query)

    final_answer, _ = _looped_answer(query, out.answer, out.routed_to, out.escalated)

    assert out.routed_to == "escalate"
    assert out.escalated is True
    assert final_answer.strip() != ""
    assert "[ESCALATE]" in final_answer


@pytest.mark.asyncio
async def test_eval_general_support_routes_support_and_returns_answer() -> None:
    query = "How do I update my email address on my account?"
    customer_id = "support-user@example.com"
    support = _StubSpecialist("You can update your email in Account Settings > Profile.")
    billing = _StubSpecialist("billing answer")
    returns = _StubSpecialist("returns answer")

    with patch("src.agents.router_agent.genai_api_configured", return_value=False):
        router = RouterAgent(
            billing=billing,
            support=support,
            returns=returns,
        )
        out = await router.route_with_meta(customer_id, query)

    final_answer, _ = _looped_answer(query, out.answer, out.routed_to, out.escalated)

    assert out.routed_to == "support"
    assert out.escalated is False
    support.handle.assert_awaited_once_with(customer_id, query)
    billing.handle.assert_not_awaited()
    returns.handle.assert_not_awaited()
    assert "email" in final_answer.lower()
