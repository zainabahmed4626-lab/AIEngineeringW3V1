"""Local Python MCP server for project diagnostics."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastmcp import FastMCP


def _load_env_files() -> None:
    project_root = Path(__file__).resolve().parents[3]
    workspace_root = Path(__file__).resolve().parents[4]

    # Prefer explicit env files if present
    load_dotenv(dotenv_path=workspace_root / ".env", override=False)
    load_dotenv(dotenv_path=project_root / ".env", override=False)


_load_env_files()

mcp = FastMCP("multi-agent-python-mcp")


@mcp.tool
def ping() -> str:
    """Return a simple heartbeat response."""
    return "pong"


@mcp.tool
def project_info() -> dict[str, str]:
    """Return quick project/runtime metadata."""
    return {
        "project": "multi_agent_customer_support",
        "python": os.sys.version.split()[0],
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }


@mcp.tool
def supabase_env_status() -> dict[str, bool]:
    """Tell whether Supabase env vars are present."""
    return {
        "has_supabase_url": bool(os.getenv("SUPABASE_URL")),
        "has_supabase_key": bool(os.getenv("SUPABASE_KEY")),
        "has_supabase_access_token": bool(os.getenv("SUPABASE_ACCESS_TOKEN")),
    }


if __name__ == "__main__":
    mcp.run()
