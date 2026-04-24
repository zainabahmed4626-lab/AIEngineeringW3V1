"""Shared MCP tool allowlist guard used by specialist agents."""

from __future__ import annotations


def ensure_tool_allowed(tool_name: str, allowed: set[str]) -> None:
    """Raise when an MCP tool is not in the agent's explicit allowlist."""
    if tool_name not in allowed:
        allowed_list = ", ".join(sorted(allowed))
        raise PermissionError(
            f"MCP tool '{tool_name}' is not allowed. Allowed tools: {allowed_list}"
        )
