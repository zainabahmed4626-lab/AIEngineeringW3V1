"""Multi-agent customer support: FastAPI API + optional interactive CLI.

Run the HTTP API (from ``multi_agent_customer_support/``)::

    uvicorn src.main:app --reload --port 8000

Run the stdin CLI (same cwd; loads ``.env`` from the workspace)::

    python -m src.main

Environment:

- ``RETURNS_SERVICE_URL`` — returns microservice base URL (default ``http://127.0.0.1:8081``).
- ``CLI_CUSTOMER_ID`` — default customer id (email or UUID) for the CLI when set.
- ``GEMINI_API_KEY`` / ``GOOGLE_API_KEY`` — router + specialists.
- Supabase: ``SUPABASE_URL``, ``SUPABASE_ANON_KEY`` (see ``src/mcp/supabase_client.py``).

Wiring:

- ``RouterAgent`` receives ``BillingAgent``, ``SupportAgent``, and ``ReturnsRemoteAgent`` explicitly.
- ``ReturnsRemoteAgent`` talks to the **A2A** returns service at ``RETURNS_SERVICE_URL``.
- Billing/support use in-process tools matching the Supabase MCP server; ``get_supabase_mcp_toolset()`` builds an
  ADK ``McpToolset`` for a **stdio** MCP connection to ``src.mcp.supabase_mcp_server`` when you need the real MCP client.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel

from google.adk.tools.mcp_tool.mcp_toolset import McpToolset

from .agents.billing_agent import BillingAgent
from .agents.loop_agent import LoopAgent
from .agents.returns_remote_agent import ReturnsRemoteAgent
from .agents.router_agent import RouterAgent
from .agents.support_agent import SupportAgent
from .mcp.supabase_mcp_connection import build_supabase_mcp_toolset
from .mcp.supabase_mcp_server import SupabaseMCPServer

load_dotenv()

RETURNS_SERVICE_URL = os.getenv("RETURNS_SERVICE_URL", "http://127.0.0.1:8081")

# --- Specialists + router (single shared graph for the API process) ---
billing_agent = BillingAgent()
support_agent = SupportAgent()
returns_remote_agent = ReturnsRemoteAgent(RETURNS_SERVICE_URL)
loop_agent = LoopAgent()
router_agent = RouterAgent(
    billing=billing_agent,
    support=support_agent,
    returns=returns_remote_agent,
)

supabase_mcp = SupabaseMCPServer()

# Lazy MCP stdio client (Supabase MCP server subprocess connects when tools are first resolved).
_supabase_mcp_toolset: McpToolset | None = None


def _debug_mode_enabled() -> bool:
    """Return True when debug logs should include LoopAgent review notes."""
    return (os.getenv("DEBUG", "") or os.getenv("APP_DEBUG", "")).lower() in {"1", "true", "yes", "on"}


def _finalize_with_loop(query: str, out: Any) -> str:
    """
    Refine specialist responses through LoopAgent before user display.

    Routing remains unchanged: only specialist outputs are loop-processed. Escalation messages pass
    through as-is so operational signaling remains explicit.
    """
    if out.routed_to not in {"billing", "support", "returns"}:
        return out.answer

    context = {
        "routed_to": out.routed_to,
        "metadata": {
            "escalate": out.escalated,
            "rationale": out.rationale,
        },
    }
    reviewed = loop_agent.process(query=query, raw_answer=out.answer, context=context)

    if _debug_mode_enabled():
        print(f"[loop] review_notes={reviewed.get('review_notes', [])!r}")

    return str(reviewed.get("final_answer", out.answer))


def get_supabase_mcp_toolset() -> McpToolset:
    """Return the shared ADK ``McpToolset`` for the Supabase MCP stdio server."""
    global _supabase_mcp_toolset
    if _supabase_mcp_toolset is None:
        _supabase_mcp_toolset = build_supabase_mcp_toolset()
    return _supabase_mcp_toolset


app = FastAPI(title="Multi-Agent Customer Support")


class SupportQuery(BaseModel):
    customer_id: str
    message: str


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "returns_service_url": RETURNS_SERVICE_URL,
        "supabase": supabase_mcp.health(),
        "agents": {
            "router": "RouterAgent",
            "billing": "BillingAgent",
            "support": "SupportAgent",
            "returns": "ReturnsRemoteAgent (A2A)",
        },
        "mcp": {
            "supabase_stdio_toolset": "lazy singleton via get_supabase_mcp_toolset()",
            "tools": ["get_billing_info", "get_support_tickets"],
        },
    }


@app.post("/support/query")
async def support_query(payload: SupportQuery) -> dict[str, Any]:
    """
    Route ``message`` for ``customer_id`` through :meth:`RouterAgent.route_with_meta`.
    """
    out = await router_agent.route_with_meta(payload.customer_id, payload.message)
    final_answer = _finalize_with_loop(payload.message, out)
    return {
        "result": final_answer,
        "routed_to": out.routed_to,
        "escalated": out.escalated,
        "rationale": out.rationale,
    }


def _cli_customer_id() -> str:
    cid = (os.getenv("CLI_CUSTOMER_ID") or "").strip()
    if cid:
        return cid
    try:
        return input("Customer id (email or UUID) [demo@example.com]: ").strip() or "demo@example.com"
    except EOFError:
        return "demo@example.com"


async def _cli_loop_async() -> None:
    """
    Simple REPL: stdin lines -> RouterAgent -> print answer + routing metadata.

    Ensures the Supabase MCP toolset object is created so the MCP client wiring is initialized
    (actual stdio subprocess may still start only when tools are loaded by a consumer).
    """
    load_dotenv()
    _ = get_supabase_mcp_toolset()

    customer_id = _cli_customer_id()
    print("Interactive support CLI. Type quit / exit to stop.")
    print(f"Using customer_id={customer_id!r} (set CLI_CUSTOMER_ID to skip prompt)\n")

    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line.lower() in ("quit", "exit", "q"):
            break

        out = await router_agent.route_with_meta(customer_id, line)
        final_answer = _finalize_with_loop(line, out)
        print(final_answer)
        print(f"[meta] routed_to={out.routed_to!r} escalated={out.escalated}")
        if out.rationale:
            print(f"[meta] rationale={out.rationale!r}")
        print()


def run_cli() -> None:
    """Entry for ``python -m src.main``."""
    asyncio.run(_cli_loop_async())


if __name__ == "__main__":
    run_cli()
