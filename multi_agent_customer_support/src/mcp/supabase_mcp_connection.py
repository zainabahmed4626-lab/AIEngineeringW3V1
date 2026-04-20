"""ADK ``McpToolset`` factory for the Supabase MCP stdio server (separate process).

Billing/support agents in this repo call the same tool implementations in-process
(``FunctionTool`` + ``supabase_mcp_server``). This toolset is for hosts that want a **real**
stdio MCP connection (e.g. future refactors, diagnostics).

The server is started as::

    python -m src.mcp.supabase_mcp_server

from the ``multi_agent_customer_support`` package root (``cwd`` below).
"""

from __future__ import annotations

import sys
from pathlib import Path

from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from mcp import StdioServerParameters

# src/mcp/supabase_mcp_connection.py -> parents[2] = multi_agent_customer_support
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent


def build_supabase_mcp_toolset() -> McpToolset:
    """Configure MCP client for ``get_billing_info`` and ``get_support_tickets`` on the Supabase server."""
    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=sys.executable,
                args=["-m", "src.mcp.supabase_mcp_server"],
                cwd=str(_PACKAGE_ROOT),
            ),
            timeout=30.0,
        ),
        tool_filter=["get_billing_info", "get_support_tickets"],
    )
