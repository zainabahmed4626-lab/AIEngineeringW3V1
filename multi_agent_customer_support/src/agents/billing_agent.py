"""Billing specialist agent: ADK ``LlmAgent`` + Supabase MCP tool functions (same impl as MCP server)."""

from __future__ import annotations

import json
import os
from typing import Any

from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools.function_tool import FunctionTool

from src.mcp.supabase_mcp_server import get_billing_info, get_support_tickets

from .adk_runtime import genai_api_configured, run_llm_agent_once
from .customer_context import resolve_customer_email


def _billing_tools() -> list[Any]:
    """Expose MCP-parity tools to the LLM via ADK ``FunctionTool`` wrappers."""
    return [
        FunctionTool(get_billing_info),
        FunctionTool(get_support_tickets),
    ]


_BILLING_INSTRUCTION = """You are a billing assistant for an e-commerce company.

You have tools that mirror the Supabase MCP server:
- ``get_billing_info(email)`` — JSON with customer orders (order_number, total_amount, status).
- ``get_support_tickets(email)`` — JSON list of support tickets.

Rules:
1. The user message includes the **resolved customer email**. Always pass that exact email string to tools.
2. Call the tools when you need factual data; do not invent amounts or order numbers.
3. Reply in concise, friendly natural language summarizing billing status and any open billing-related tickets.
4. If JSON shows ``customer_not_found``, say we could not match an account and ask them to verify their email.
"""


class BillingAgent:
    """
    Handles billing-related questions using Gemini + tool calls.

    Tools implement the same behavior as ``src/mcp/supabase_mcp_server.py`` (stdio MCP is optional;
    in-process calls keep tests and local dev simple).
    """

    def __init__(self, model: str | None = None) -> None:
        self._model = model or os.getenv("ADK_MODEL", "gemini-2.5-flash")
        self._agent = LlmAgent(
            name="billing_agent",
            model=self._model,
            instruction=_BILLING_INSTRUCTION,
            tools=_billing_tools(),
        )

    async def handle(self, customer_id: str, message: str) -> str:
        """
        Answer a billing question for ``customer_id`` (UUID or email) and user ``message``.

        Uses the LLM when ``GOOGLE_API_KEY`` / ``GEMINI_API_KEY`` is set; otherwise returns a
        deterministic summary from the same tool functions.
        """
        email = resolve_customer_email(customer_id)
        if not email:
            return (
                "We could not resolve an email address for this customer id. "
                "Please provide a customer id that exists in our system or use your account email."
            )

        if not genai_api_configured():
            billing_json = get_billing_info(email)
            tickets_json = get_support_tickets(email)
            return _format_billing_fallback(billing_json, tickets_json, message)

        user_prompt = (
            f"Resolved customer email (use for tool calls): {email}\n"
            f"Customer id (reference): {customer_id}\n\n"
            f"User question:\n{message}\n"
        )
        return await run_llm_agent_once(
            agent=self._agent,
            user_message=user_prompt,
            app_name="billing",
        )


def _format_billing_fallback(billing_json: str, tickets_json: str, message: str) -> str:
    """Readable summary without an LLM (offline / CI)."""
    try:
        billing = json.loads(billing_json)
        tickets_payload = json.loads(tickets_json)
    except json.JSONDecodeError:
        return "[BillingAgent] Unable to parse billing data."

    lines = [
        "[BillingAgent — offline summary]",
        f'Your question: "{message[:200]}"',
        "",
    ]

    if billing.get("error") == "customer_not_found":
        lines.append("No customer record found for that email.")
        return "\n".join(lines)

    cust = billing.get("customer") or {}
    lines.append(f"Customer: {cust.get('name', 'Unknown')} ({cust.get('email', '')})")
    orders = billing.get("orders") or []
    if not orders:
        lines.append("No orders on file.")
    else:
        lines.append(f"Orders ({len(orders)}):")
        for o in orders[:10]:
            lines.append(
                f"  - {o.get('order_number')}: "
                f"amount={o.get('total_amount')}, status={o.get('status')}"
            )
        if len(orders) > 10:
            lines.append(f"  … and {len(orders) - 10} more.")

    tickets = tickets_payload.get("tickets") or []
    lines.append("")
    lines.append(f"Support tickets on file: {len(tickets)}.")
    return "\n".join(lines)
