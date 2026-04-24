"""General support agent: reads tickets via MCP-parity tools and guides or escalates."""

from __future__ import annotations

import json
import os
from typing import Any

from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools.function_tool import FunctionTool

from src.mcp.supabase_mcp_server import get_support_tickets

from .adk_runtime import genai_api_configured, looks_like_genai_quota_error, run_llm_agent_once
from .customer_context import resolve_customer_email
from .tool_filter import ensure_tool_allowed

ALLOWED_MCP_TOOLS = {"get_billing_info", "get_support_tickets"}


def _call_allowed_tool(tool_name: str, email: str) -> str:
    """
    Guard and invoke a read-only MCP-parity tool by name.

    SupportAgent currently uses only `get_support_tickets`, but keeps a shared allowlist shape.
    """
    ensure_tool_allowed(tool_name, ALLOWED_MCP_TOOLS)
    if tool_name == "get_support_tickets":
        return get_support_tickets(email)
    raise ValueError(f"Unsupported tool mapping for {tool_name!r}")


def _get_support_tickets_guarded(email: str) -> str:
    return _call_allowed_tool("get_support_tickets", email)


def _support_tools() -> list[Any]:
    return [
        FunctionTool(_get_support_tickets_guarded),
    ]


_SUPPORT_INSTRUCTION = """You are a careful customer-support assistant.

You have one factual tool:
- ``get_support_tickets(email)`` — returns JSON with ``tickets`` for that customer.

Guidelines:
1. Use the **resolved email** provided in the user message for ``get_support_tickets``.
2. Summarize ticket status at a high level (subject/category if present); do not fabricate ticket IDs.
3. For abuse, threats, legal threats, suspected fraud, or account compromise, clearly recommend **human escalation**.
4. Keep answers concise and professional.
"""


class SupportAgent:
    """Generic support flow with optional Gemini; offline mode summarizes tickets without an LLM."""

    def __init__(self, model: str | None = None) -> None:
        self._model = model or os.getenv("ADK_MODEL", "gemini-2.5-flash")
        self._agent = LlmAgent(
            name="support_agent",
            model=self._model,
            instruction=_SUPPORT_INSTRUCTION,
            tools=_support_tools(),
        )

    async def handle(self, customer_id: str, message: str) -> str:
        email = resolve_customer_email(customer_id)
        if not email:
            return (
                "We could not resolve an email for this customer id. "
                "Please contact support with your registered email."
            )

        if not genai_api_configured():
            tickets_json = _call_allowed_tool("get_support_tickets", email)
            return _format_support_fallback(tickets_json, message)

        user_prompt = (
            f"Resolved customer email (use for tool calls): {email}\n"
            f"Customer id (reference): {customer_id}\n\n"
            f"User message:\n{message}\n"
        )
        try:
            return await run_llm_agent_once(
                agent=self._agent,
                user_message=user_prompt,
                app_name="support",
            )
        except Exception as exc:
            if looks_like_genai_quota_error(exc):
                tickets_json = _call_allowed_tool("get_support_tickets", email)
                base = _format_support_fallback(tickets_json, message)
                return (
                    f"{base}\n\n"
                    "[Note] Gemini quota or rate limit was hit; this summary was built "
                    "directly from support tickets without the LLM."
                )
            raise


def _format_support_fallback(tickets_json: str, message: str) -> str:
    try:
        payload = json.loads(tickets_json)
    except json.JSONDecodeError:
        return "[SupportAgent] Unable to parse ticket data."

    lines = [
        "[SupportAgent — offline summary]",
        f'Your message: "{message[:200]}"',
        "",
    ]

    if payload.get("error") == "customer_not_found":
        lines.append("No matching customer email in our records.")
        return "\n".join(lines)

    tickets = payload.get("tickets") or []
    lines.append(f"Open/recent tickets in view: {len(tickets)}.")
    for t in tickets[:5]:
        subj = t.get("subject") or t.get("title") or "(no subject)"
        cat = t.get("category", "")
        stat = t.get("status", "")
        lines.append(f"  - [{stat}] {cat}: {subj}")
    if len(tickets) > 5:
        lines.append(f"  … and {len(tickets) - 5} more.")

    lines.append("")
    lines.append(
        "If this involves threats, legal action, or account security, request a human specialist."
    )
    return "\n".join(lines)
