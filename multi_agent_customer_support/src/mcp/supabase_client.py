"""Supabase Postgres helpers for customer support data (supabase-py).

Import from the ``src`` package to avoid clashing with the PyPI ``mcp`` SDK, for example:

    from src.mcp.supabase_client import get_customer_by_email

This matches running the API with ``uvicorn src.main:app`` from ``multi_agent_customer_support/``.
"""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv

try:
    from supabase import Client, create_client
except ImportError as exc:  # pragma: no cover - env without supabase installed
    Client = Any  # type: ignore[misc, assignment]
    create_client = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


class SupabaseConfigurationError(RuntimeError):
    """Raised when URL/key are missing or the Supabase SDK is unavailable."""


def _load_dotenv() -> None:
    """Load `.env` from typical locations (workspace root + package root)."""
    try:
        from pathlib import Path

        here = Path(__file__).resolve()
        package_root = here.parents[2]
        workspace_root = here.parents[3]
        load_dotenv(dotenv_path=workspace_root / ".env", override=False)
        load_dotenv(dotenv_path=package_root / ".env", override=False)
    except Exception:
        load_dotenv(override=False)


_load_dotenv()

_client: Client | None = None


def _resolve_anon_key() -> str:
    """Prefer SUPABASE_ANON_KEY; fall back to SUPABASE_KEY for older configs."""
    return (os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_KEY") or "").strip()


def _require_sdk() -> None:
    if create_client is None:
        raise SupabaseConfigurationError(
            "supabase-py is not installed or failed to import."
        ) from _IMPORT_ERROR


def get_supabase_client() -> Client:
    """
    Return a cached Supabase client using ``SUPABASE_URL`` and ``SUPABASE_ANON_KEY``.

    ``SUPABASE_KEY`` is accepted as a fallback when ``SUPABASE_ANON_KEY`` is unset.
    """
    global _client
    _require_sdk()

    if _client is not None:
        return _client

    url = (os.getenv("SUPABASE_URL") or "").strip()
    key = _resolve_anon_key()
    if not url or not key:
        raise SupabaseConfigurationError(
            "Set SUPABASE_URL and SUPABASE_ANON_KEY (or SUPABASE_KEY) in the environment."
        )

    assert create_client is not None
    _client = create_client(url, key)
    return _client


def reset_supabase_client_cache() -> None:
    """Clear the cached client (mainly for tests)."""
    global _client
    _client = None


def get_customer_by_email(email: str) -> dict[str, Any] | None:
    """
    Fetch a single customer row by unique email.

    :param email: Customer email (trimmed); must be non-empty.
    :returns: One row as a dict, or ``None`` if not found.
    :raises SupabaseConfigurationError: If env or SDK is not usable.
    :raises ValueError: If ``email`` is empty.
    """
    email_clean = (email or "").strip()
    if not email_clean:
        raise ValueError("email must be a non-empty string")

    try:
        client = get_supabase_client()
        response = (
            client.table("customers")
            .select("*")
            .eq("email", email_clean)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None
    except SupabaseConfigurationError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Failed to load customer by email: {exc}") from exc


def get_customer_by_id(customer_id: str) -> dict[str, Any] | None:
    """
    Fetch a single customer row by primary key ``id`` (UUID string).

    :param customer_id: ``customers.id`` as a string.
    :returns: One row as a dict, or ``None`` if not found.
    :raises SupabaseConfigurationError: If env or SDK is not usable.
    :raises ValueError: If ``customer_id`` is empty.
    """
    cid = (customer_id or "").strip()
    if not cid:
        raise ValueError("customer_id must be a non-empty string")

    try:
        client = get_supabase_client()
        response = (
            client.table("customers")
            .select("*")
            .eq("id", cid)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None
    except SupabaseConfigurationError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Failed to load customer by id: {exc}") from exc


def get_orders_by_customer(customer_id: str) -> list[dict[str, Any]]:
    """
    List orders for a customer (newest first by ``created_at``).

    :param customer_id: UUID string for ``orders.customer_id``.
    :returns: List of order rows (possibly empty).
    :raises SupabaseConfigurationError: If env or SDK is not usable.
    :raises ValueError: If ``customer_id`` is empty.
    """
    cid = (customer_id or "").strip()
    if not cid:
        raise ValueError("customer_id must be a non-empty string")

    try:
        client = get_supabase_client()
        response = (
            client.table("orders")
            .select("*")
            .eq("customer_id", cid)
            .order("created_at", desc=True)
            .execute()
        )
        return list(response.data or [])
    except SupabaseConfigurationError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Failed to list orders for customer: {exc}") from exc


def get_support_tickets_by_customer(customer_id: str) -> list[dict[str, Any]]:
    """
    List support tickets for a customer (newest first by ``created_at``).

    :param customer_id: UUID string for ``support_tickets.customer_id``.
    :returns: List of ticket rows (possibly empty).
    :raises SupabaseConfigurationError: If env or SDK is not usable.
    :raises ValueError: If ``customer_id`` is empty.
    """
    cid = (customer_id or "").strip()
    if not cid:
        raise ValueError("customer_id must be a non-empty string")

    try:
        client = get_supabase_client()
        response = (
            client.table("support_tickets")
            .select("*")
            .eq("customer_id", cid)
            .order("created_at", desc=True)
            .execute()
        )
        return list(response.data or [])
    except SupabaseConfigurationError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Failed to list support tickets for customer: {exc}") from exc


def get_support_tickets_by_category(category: str) -> list[dict[str, Any]]:
    """
    List support tickets matching a category (e.g. ``billing``, ``returns``, ``general``).

    :param category: Ticket category string.
    :returns: List of ticket rows (possibly empty).
    :raises SupabaseConfigurationError: If env or SDK is not usable.
    :raises ValueError: If ``category`` is empty.
    """
    cat = (category or "").strip()
    if not cat:
        raise ValueError("category must be a non-empty string")

    try:
        client = get_supabase_client()
        response = (
            client.table("support_tickets")
            .select("*")
            .eq("category", cat)
            .order("created_at", desc=True)
            .execute()
        )
        return list(response.data or [])
    except SupabaseConfigurationError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Failed to list support tickets: {exc}") from exc
