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

from google.adk.agents.remote_a2a_agent import RemoteA2aAgent

from .adk_runtime import run_llm_agent_once

logger = logging.getLogger(__name__)

# Stable name for Runner / events (must match RemoteA2aAgent instance name for logging clarity).
_RETURNS_REMOTE_NAME = "returns_service_a2a"

_APP_NAME = "returns_a2a_client"


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
        text = await run_llm_agent_once(
            agent=self._remote,
            user_message=prompt,
            app_name=_APP_NAME,
        )
        try:
            data = _parse_json_object(text)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Failed to parse eligibility JSON: %s — raw: %s", exc, text[:500])
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
        text = await run_llm_agent_once(
            agent=self._remote,
            user_message=prompt,
            app_name=_APP_NAME,
        )
        try:
            data = _parse_json_object(text)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Failed to parse initiate_return JSON: %s — raw: %s", exc, text[:500])
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
        return await run_llm_agent_once(
            agent=self._remote,
            user_message=prompt,
            app_name=_APP_NAME,
        )
