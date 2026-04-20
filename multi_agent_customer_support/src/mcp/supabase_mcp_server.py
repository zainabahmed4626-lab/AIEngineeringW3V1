"""Supabase-backed MCP server for ADK agents (Model Context Protocol tools over stdio).

This process exposes tools that query Postgres via ``supabase-py``. Run it as a **separate
process** and point Google ADK / MCP clients at this server (stdio transport).

How to run (from ``multi_agent_customer_support/``):

    .venv\\Scripts\\activate
    python -m src.mcp.supabase_mcp_server

Environment (same as ``supabase_client``):

- ``SUPABASE_URL``
- ``SUPABASE_ANON_KEY`` (or legacy ``SUPABASE_KEY``)

Ensure Row Level Security policies allow the ``anon`` role to read the relevant tables
(see ``sql/fix_rls_and_verify.sql``).
"""

from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv
from fastmcp import FastMCP

from .supabase_client import (
    SupabaseConfigurationError,
    get_customer_by_email,
    get_orders_by_customer,
    get_support_tickets_by_customer,
    get_supabase_client,
)

# Load workspace / package .env before tools run (FastMCP subprocess may not inherit shell env).
try:
    from pathlib import Path

    _here = Path(__file__).resolve()
    _pkg = _here.parents[2]
    _ws = _here.parents[3]
    load_dotenv(dotenv_path=_ws / ".env", override=False)
    load_dotenv(dotenv_path=_pkg / ".env", override=False)
except Exception:
    load_dotenv(override=False)


mcp = FastMCP("supabase-support-mcp")


@mcp.tool()
def get_billing_info(email: str) -> str:
    """
    Look up a customer by email and return a concise JSON summary of their orders
    (billing-related: ``order_number``, ``total_amount``, ``status``).

    Returns a JSON string for easy consumption by agents.
    """
    email_clean = (email or "").strip()
    if not email_clean:
        return json.dumps({"error": "invalid_email", "message": "email must be non-empty"})

    customer = get_customer_by_email(email_clean)
    if not customer:
        return json.dumps(
            {"error": "customer_not_found", "email": email_clean, "orders": []}
        )

    customer_id = str(customer.get("id", ""))
    orders_raw = get_orders_by_customer(customer_id)

    orders = []
    for row in orders_raw:
        amt = row.get("total_amount")
        try:
            total = float(amt) if amt is not None else None
        except (TypeError, ValueError):
            total = amt
        orders.append(
            {
                "order_number": row.get("order_number"),
                "total_amount": total,
                "status": row.get("status"),
            }
        )

    payload = {
        "customer": {
            "id": customer_id,
            "name": customer.get("name"),
            "email": customer.get("email"),
        },
        "orders": orders,
        "order_count": len(orders),
    }
    return json.dumps(payload, default=str)


@mcp.tool()
def get_support_tickets(email: str) -> str:
    """
    Look up a customer by email and return all ``support_tickets`` for that customer.

    Returns a JSON string containing ``customer`` metadata and a ``tickets`` list.
    """
    email_clean = (email or "").strip()
    if not email_clean:
        return json.dumps({"error": "invalid_email", "message": "email must be non-empty"})

    customer = get_customer_by_email(email_clean)
    if not customer:
        return json.dumps(
            {
                "error": "customer_not_found",
                "email": email_clean,
                "tickets": [],
            }
        )

    customer_id = str(customer.get("id", ""))
    tickets = get_support_tickets_by_customer(customer_id)

    payload = {
        "customer": {
            "id": customer_id,
            "name": customer.get("name"),
            "email": customer.get("email"),
        },
        "tickets": tickets,
        "ticket_count": len(tickets),
    }
    return json.dumps(payload, default=str)


class SupabaseMCPServer:
    """Lightweight health helper used by ``src.main`` FastAPI (not the MCP stdio server)."""

    def health(self) -> dict[str, Any]:
        try:
            get_supabase_client()
            return {
                "configured": True,
                "sdk_available": True,
                "supabase_url_set": bool(os.getenv("SUPABASE_URL")),
                "anon_or_key_set": bool(
                    os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_KEY")
                ),
            }
        except SupabaseConfigurationError as exc:
            return {
                "configured": False,
                "sdk_available": True,
                "error": str(exc),
            }


def main() -> None:
    """
    Start the MCP server (default: **stdio** transport).

    Run as a dedicated process; ADK / MCP hosts spawn this executable and communicate
    over stdin/stdout per the Model Context Protocol.
    """
    mcp.run()


if __name__ == "__main__":
    main()
