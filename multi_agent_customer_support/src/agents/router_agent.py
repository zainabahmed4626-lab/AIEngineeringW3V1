"""Router agent (root): classifies NL queries and delegates to domain agents."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from google.adk.agents.llm_agent import LlmAgent
from pydantic import BaseModel, Field

from .adk_runtime import genai_api_configured, run_router_structured
from .billing_agent import BillingAgent
from .returns_remote_agent import ReturnsRemoteAgent
from .support_agent import SupportAgent


@dataclass
class RouterOutcome:
    """Result of :meth:`RouterAgent.route_with_meta` (answer + routing metadata for CLI/API)."""

    answer: str
    routed_to: Literal["billing", "returns", "support", "escalate"]
    escalated: bool
    rationale: str | None = None


class RouterDecision(BaseModel):
    """Structured router output when Gemini is available (matches ``output_schema``)."""

    route: Literal["billing", "returns", "support"] = Field(
        ...,
        description="Exactly one downstream agent to handle this turn.",
    )
    escalate: bool = Field(False, description="True if a human specialist should take over.")
    rationale: str = Field("", description="Short justification for auditing.")


# Prompt + few-shot exemplars teach the small model routing boundaries without extra tooling.
_ROUTER_FEW_SHOT = """
Examples (follow the same routing rules for new inputs):

User: Where can I download last month's VAT invoice?
Assistant JSON: {"route":"billing","escalate":false,"rationale":"invoice / billing document"}

User: My card was charged twice for order #4412.
Assistant JSON: {"route":"billing","escalate":false,"rationale":"duplicate charge"}

User: I want to return sneakers and print a prepaid label.
Assistant JSON: {"route":"returns","escalate":false,"rationale":"return + label"}

User: Am I eligible to return clearance items opened last week?
Assistant JSON: {"route":"returns","escalate":false,"rationale":"returns eligibility"}

User: The app freezes when I open notifications — generic bug.
Assistant JSON: {"route":"support","escalate":false,"rationale":"general product issue"}

User: I'm going to sue your company unless I get my money today!!!
Assistant JSON: {"route":"support","escalate":true,"rationale":"legal threat / high severity"}

User: ???
Assistant JSON: {"route":"support","escalate":true,"rationale":"unclear intent"}
"""


ROUTER_SYSTEM_INSTRUCTION = f"""You are the intent router for a commerce support system.

Choose exactly one route:
- billing — invoices, charges, payments, subscriptions, receipts (money on account).
- returns — product returns, exchanges, prepaid labels, return eligibility.
- support — general troubleshooting, bugs, vague questions, shipping status *unless* it is clearly billing or returns.

Set escalate=true when:
- The user is furious, threatens legal action, mentions lawyers/police/regulators,
- Self-harm or abuse is hinted,
- The request is too ambiguous to route safely,

Output **only JSON** matching the schema (route, escalate, rationale). No markdown fences.

{_ROUTER_FEW_SHOT}
"""


def classify_intent_fallback(message: str) -> RouterDecision:
    """
    Keyword + heuristic router used when Gemini is not configured or JSON parsing fails.

    Kept deterministic for CI and for environments without ``GOOGLE_API_KEY``.
    """
    lower = (message or "").lower().strip()

    escalate_terms = (
        "lawsuit",
        "lawyer",
        "attorney",
        "sue ",
        " suing",
        "police",
        "fcc",
        " regulator",
        "suicide",
        "self-harm",
        "kill myself",
        "discriminat",
    )
    if any(t in lower for t in escalate_terms):
        return RouterDecision(
            route="support",
            escalate=True,
            rationale="potential high-severity / legal / safety keywords",
        )

    if any(
        k in lower
        for k in (
            "return",
            "exchange",
            "label",
            "ship back",
            "send back",
            "wrong item",
            "didn't fit",
            "doesn't fit",
            " rma",
        )
    ):
        return RouterDecision(route="returns", escalate=False, rationale="returns-flow keywords")

    billing_terms = (
        "invoice",
        "bill",
        "billing",
        "charge",
        "charged",
        "payment",
        "subscription",
        "receipt",
        "refund",
        "card",
        "paypal",
        "vat",
        "statement",
        "duplicate charge",
        "overcharge",
    )
    if any(k in lower for k in billing_terms):
        return RouterDecision(route="billing", escalate=False, rationale="billing/payment keywords")

    if len(lower) < 4:
        return RouterDecision(route="support", escalate=True, rationale="message too short / unclear")

    return RouterDecision(route="support", escalate=False, rationale="default general support")


class RouterAgent:
    """
    Root agent: uses Gemini + few-shot JSON classification when keys exist; otherwise heuristics.

    Construct with explicit specialist agents (wired in ``main.py``):

    - ``billing`` — :class:`BillingAgent` (Supabase tool functions / MCP parity)
    - ``returns`` — :class:`ReturnsRemoteAgent` (remote returns A2A service)
    - ``support`` — :class:`SupportAgent`
    """

    def __init__(
        self,
        *,
        billing: BillingAgent,
        support: SupportAgent,
        returns: ReturnsRemoteAgent,
        model: str | None = None,
    ) -> None:
        self._model = model or os.getenv("ADK_MODEL", "gemini-2.5-flash")
        self.billing = billing
        self.support = support
        self.returns = returns

        self._router_llm = LlmAgent(
            name="router",
            model=self._model,
            instruction=ROUTER_SYSTEM_INSTRUCTION,
            output_schema=RouterDecision,
        )

    async def route_with_meta(self, customer_id: str, message: str) -> RouterOutcome:
        """
        Classify ``message``, dispatch to the right specialist, return answer + metadata.

        Use this from the CLI and from APIs that need ``routed_to`` / ``escalated``.
        """
        router_input = (
            "Classify this customer turn.\n\n"
            f"customer_id: {customer_id}\n\n"
            f"message:\n{message}\n"
        )

        decision: RouterDecision | None = None
        if genai_api_configured():
            decision = await run_router_structured(
                agent=self._router_llm,
                user_message=router_input,
                schema_type=RouterDecision,
                app_name="router",
            )

        if decision is None:
            decision = classify_intent_fallback(message)

        if decision.escalate:
            text = (
                "[ESCALATE]\n"
                "This request was flagged for a human specialist.\n"
                f"Routing note: {decision.rationale}\n"
                "ESCALATE_FLAG: true"
            )
            return RouterOutcome(
                answer=text,
                routed_to="escalate",
                escalated=True,
                rationale=decision.rationale,
            )

        if decision.route == "billing":
            ans = await self.billing.handle(customer_id, message)
            return RouterOutcome(
                answer=ans,
                routed_to="billing",
                escalated=False,
                rationale=decision.rationale,
            )

        if decision.route == "returns":
            ans = await self.returns.handle(customer_id, message)
            return RouterOutcome(
                answer=ans,
                routed_to="returns",
                escalated=False,
                rationale=decision.rationale,
            )

        ans = await self.support.handle(customer_id, message)
        return RouterOutcome(
            answer=ans,
            routed_to="support",
            escalated=False,
            rationale=decision.rationale,
        )

    async def route(self, customer_id: str, message: str) -> str:
        """
        Classify ``message`` and invoke the appropriate agent (answer text only).

        Escalations return a body containing ``[ESCALATE]`` and ``ESCALATE_FLAG: true``.
        """
        return (await self.route_with_meta(customer_id, message)).answer
