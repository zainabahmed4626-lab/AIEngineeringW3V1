"""Remote returns integration via ADK ``RemoteA2aAgent`` (A2A JSON-RPC to the returns service).

The returns microservice (``servers/returns_service/main.py``) exposes an ADK ``LlmAgent`` over A2A
with tools ``check_return_eligibility`` and ``initiate_return``. This module wraps that remote
agent so the rest of the app can call those tools without speaking JSON-RPC directly.

**RouterAgent usage**

``RouterAgent`` routes returns-related NL queries here via :meth:`handle`::

    # Inside RouterAgent.route (returns branch):
    return await self.returns.handle(customer_id, message)

For **structured** calls (tests, future tooling), use :meth:`check_return_eligibility` and
:meth:`initiate_return` — they send explicit instructions over the same A2A link so the *remote*
model invokes the matching tool and we parse JSON from the reply.

**Requirements**

- Returns service running (default ``http://127.0.0.1:8081``).
- Agent card reachable at ``{base_url}/.well-known/agent-card.json`` (or set ``RETURNS_A2A_AGENT_CARD_URL``).
- Remote service must have ``GEMINI_API_KEY`` / ``GOOGLE_API_KEY`` so its LlmAgent can run tools.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent

from .adk_runtime import run_llm_agent_once

logger = logging.getLogger(__name__)

# Stable name for Runner / events (must match RemoteA2aAgent instance name for logging clarity).
_RETURNS_REMOTE_NAME = "returns_service_a2a"

_APP_NAME = "returns_a2a_client"
_ORDER_RE = re.compile(r"\bORD-\d{4}-\d+\b", re.IGNORECASE)


def _default_agent_card_url(base_url: str) -> str:
    """Resolve Agent Card URL; override with ``RETURNS_A2A_AGENT_CARD_URL`` for proxies."""
    explicit = (os.getenv("RETURNS_A2A_AGENT_CARD_URL") or "").strip()
    if explicit:
        return explicit
    return f"{base_url.rstrip('/')}/.well-known/agent-card.json"


def _parse_json_object(text: str) -> dict[str, Any]:
    """Best-effort parse of a single JSON object from model text (may include markdown fences)."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("empty response from remote A2A agent")

    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()

    try:
        out = json.loads(raw)
        if isinstance(out, dict):
            return out
    except json.JSONDecodeError:
        pass

    m = re.search(r"\{[\s\S]*\}", raw)
    if m:
        return json.loads(m.group(0))

    raise ValueError(f"no JSON object found in response: {raw[:300]}")


def _looks_like_quota_error(text: str) -> bool:
    s = (text or "").lower()
    return any(
        key in s
        for key in (
            "resource_exhausted",
            "quota",
            "429",
            "rate limit",
            "too many requests",
        )
    )


def _extract_order_number(message: str) -> str | None:
    m = _ORDER_RE.search(message or "")
    return m.group(0).upper() if m else None


def _wants_initiate_return(message: str) -> bool:
    s = (message or "").lower()
    return any(
        k in s
        for k in (
            "initiate return",
            "start return",
            "create return",
            "open return",
            "return this",
            "send it back",
        )
    )


class ReturnsRemoteAgent:
    """
    Client for the returns microservice using ``RemoteA2aAgent``.

    ``base_url`` is the HTTP origin of the service (e.g. ``http://127.0.0.1:8081``), *not* the
    JSON-RPC path — the Agent Card URL is derived by :func:`_default_agent_card_url`.
    """

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        card_url = _default_agent_card_url(self.base_url)
        self._remote = RemoteA2aAgent(
            name=_RETURNS_REMOTE_NAME,
            agent_card=card_url,
            description="Remote returns A2A agent (eligibility + initiate return tools)",
        )

    async def _http_tool_call(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                return data
            return {"error": "invalid_response", "detail": "tool endpoint did not return JSON object"}

    async def _fallback_handle(self, customer_id: str, message: str, reason: str) -> str:
        order_number = _extract_order_number(message)
        if not order_number:
            return (
                "I could not find an order number in your message. "
                "Please include something like ORD-2026-0008 so I can check eligibility "
                "or initiate the return."
            )

        try:
            if _wants_initiate_return(message):
                out = await self._http_tool_call(
                    "/tools/initiate_return",
                    {"order_number": order_number, "reason": message[:500]},
                )
                return (
                    f"[Returns fallback] {out.get('message', 'Return initiated.')}\n"
                    f"return_id={out.get('return_id', 'n/a')} status={out.get('status', 'n/a')}"
                )

            out = await self._http_tool_call(
                "/tools/check_return_eligibility",
                {"order_number": order_number},
            )
            eligible = bool(out.get("eligible", False))
            decision = "eligible" if eligible else "not eligible"
            return (
                f"[Returns fallback] Order {order_number} is {decision} for return.\n"
                f"Reason: {out.get('reason', 'No reason provided.')}"
            )
        except Exception as exc:
            logger.warning("Returns fallback failed for customer %s: %s", customer_id, exc)
            return (
                "Returns service is temporarily degraded and the fallback check failed. "
                "Please retry in a moment."
            )

    async def check_return_eligibility(self, order_number: str) -> dict[str, Any]:
        """
        Ask the remote agent to run ``check_return_eligibility`` for ``order_number``.

        Returns a dict with at least ``eligible`` and ``reason`` (from the remote tool output).
        """
        prompt = (
            "You must call the tool named check_return_eligibility exactly once with the "
            f"given order_number.\n\norder_number: {order_number!r}\n\n"
            "After the tool returns, reply with nothing except a single JSON object copying "
            'the tool result: {"eligible": <bool>, "reason": "<string>"}. '
            "No markdown, no explanation."
        )
        try:
            text = await run_llm_agent_once(
                agent=self._remote,
                user_message=prompt,
                app_name=_APP_NAME,
            )
        except Exception as exc:
            if _looks_like_quota_error(str(exc)):
                logger.warning("A2A quota hit; using HTTP fallback for check_return_eligibility")
                return await self._http_tool_call(
                    "/tools/check_return_eligibility",
                    {"order_number": order_number},
                )
            raise
        try:
            data = _parse_json_object(text)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Failed to parse eligibility JSON: %s — raw: %s", exc, text[:500])
            if _looks_like_quota_error(text):
                logger.warning("A2A quota text detected; using HTTP fallback for eligibility")
                return await self._http_tool_call(
                    "/tools/check_return_eligibility",
                    {"order_number": order_number},
                )
            return {"error": "parse_failed", "detail": str(exc), "raw": text[:2000]}
        return data

    async def initiate_return(self, order_number: str, reason: str) -> dict[str, Any]:
        """
        Ask the remote agent to run ``initiate_return`` for ``order_number`` and ``reason``.

        Returns a dict with ``return_id``, ``status``, and ``message`` when parsing succeeds.
        """
        prompt = (
            "You must call the tool named initiate_return exactly once with:\n"
            f"  order_number: {order_number!r}\n"
            f"  reason: {reason!r}\n\n"
            "After the tool returns, reply with nothing except a single JSON object copying "
            'the tool result: {"return_id": "<string>", "status": "initiated", "message": "<string>"}. '
            "No markdown, no explanation."
        )
        try:
            text = await run_llm_agent_once(
                agent=self._remote,
                user_message=prompt,
                app_name=_APP_NAME,
            )
        except Exception as exc:
            if _looks_like_quota_error(str(exc)):
                logger.warning("A2A quota hit; using HTTP fallback for initiate_return")
                return await self._http_tool_call(
                    "/tools/initiate_return",
                    {"order_number": order_number, "reason": reason},
                )
            raise
        try:
            data = _parse_json_object(text)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Failed to parse initiate_return JSON: %s — raw: %s", exc, text[:500])
            if _looks_like_quota_error(text):
                logger.warning("A2A quota text detected; using HTTP fallback for initiate_return")
                return await self._http_tool_call(
                    "/tools/initiate_return",
                    {"order_number": order_number, "reason": reason},
                )
            return {"error": "parse_failed", "detail": str(exc), "raw": text[:2000]}
        return data

    async def handle(self, customer_id: str, message: str) -> str:
        """
        Natural-language entry point used by **RouterAgent** for the returns branch.

        Forwards ``customer_id`` and the user ``message`` to the remote returns agent over A2A
        (same JSON-RPC channel as structured methods, without forcing JSON-only output).
        """
        prompt = (
            f"Customer id: {customer_id}\n\n"
            f"User message:\n{message}\n\n"
            "Use the returns tools as needed (check_return_eligibility, initiate_return) "
            "and answer helpfully."
        )
        try:
            text = await run_llm_agent_once(
                agent=self._remote,
                user_message=prompt,
                app_name=_APP_NAME,
            )
            if _looks_like_quota_error(text):
                logger.warning("A2A quota text detected; using returns HTTP fallback")
                return await self._fallback_handle(customer_id, message, reason="quota_text")
            return text
        except Exception as exc:
            if _looks_like_quota_error(str(exc)):
                logger.warning("A2A quota exception detected; using returns HTTP fallback")
                return await self._fallback_handle(customer_id, message, reason="quota_exception")
            raise
