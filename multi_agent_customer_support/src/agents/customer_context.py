"""Resolve end-user email for MCP tools from API ``customer_id`` (UUID or email)."""

from __future__ import annotations

from src.mcp.supabase_client import SupabaseConfigurationError, get_customer_by_id


def resolve_customer_email(customer_id: str) -> str | None:
    """
    MCP tools expect an email.

    - If ``customer_id`` looks like an email (contains ``@``), use it as-is.
    - Otherwise treat it as ``customers.id`` and look up ``email`` from Supabase.

    Returns ``None`` if lookup fails or email is missing.
    """
    raw = (customer_id or "").strip()
    if not raw:
        return None
    if "@" in raw:
        return raw

    try:
        row = get_customer_by_id(raw)
    except (SupabaseConfigurationError, ValueError, RuntimeError):
        return None

    if not row:
        return None
    email = row.get("email")
    return str(email).strip() if email else None
