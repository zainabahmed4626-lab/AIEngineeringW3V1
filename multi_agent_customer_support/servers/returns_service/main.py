"""
Returns microservice: FastAPI + A2A (Agent-to-Agent) JSON-RPC for an ADK ``LlmAgent``.

**Run locally** (from ``multi_agent_customer_support/``; activates the venv first)::

    .venv\\Scripts\\activate
    uvicorn servers.returns_service.main:app --host 127.0.0.1 --port 8081

Or::

    python -m uvicorn servers.returns_service.main:app --host 127.0.0.1 --port 8081

Environment:

- ``RETURNS_SERVICE_PORT`` — default ``8081`` (used by ``main()`` when you ``python -m servers.returns_service.main``).
- ``RETURNS_A2A_PUBLIC_URL`` — base URL embedded in the Agent Card (default ``http://127.0.0.1:8081``).
- ``GOOGLE_API_KEY`` or ``GEMINI_API_KEY`` — required for A2A ``message/send`` so the model can call tools.
- ``ADK_MODEL`` — optional override (default ``gemini-2.5-flash``).

**Example curl**

Agent card (no API key required)::

    curl -s http://127.0.0.1:8081/.well-known/agent-card.json | head

Direct mock tool endpoints (no LLM; same rules as the agent tools)::

    curl -s -X POST http://127.0.0.1:8081/tools/check_return_eligibility \\
      -H "Content-Type: application/json" -d "{\\"order_number\\": \\"ORD-42\\"}"

    curl -s -X POST http://127.0.0.1:8081/tools/initiate_return \\
      -H "Content-Type: application/json" \\
      -d "{\\"order_number\\": \\"ORD-42\\", \\"reason\\": \\"changed mind\\"}"

A2A JSON-RPC (needs Gemini for the agent to reply; body is illustrative)::

    curl -s -X POST http://127.0.0.1:8081/ \\
      -H "Content-Type: application/json" \\
      -d "{\\"jsonrpc\\":\\"2.0\\",\\"id\\":\\"1\\",\\"method\\":\\"message/send\\",\\"params\\":{\\"message\\":{\\"role\\":\\"user\\",\\"parts\\":[{\\"kind\\":\\"text\\",\\"text\\":\\"Is order ORD-42 eligible for return?\\"}],\\"message_id\\":\\"m1\\",\\"kind\\":\\"message\\"}}}"
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from typing import Any

from a2a.server.apps import A2AFastAPIApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryPushNotificationConfigStore
from a2a.server.tasks import InMemoryTaskStore
from fastapi import FastAPI
from google.adk.agents.llm_agent import LlmAgent
from google.adk.a2a.utils.agent_card_builder import AgentCardBuilder
from google.adk.a2a.utils.agent_to_a2a import to_a2a as adk_to_a2a
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.auth.credential_service.in_memory_credential_service import (
    InMemoryCredentialService,
)
from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.tools.function_tool import FunctionTool
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Mock tool implementations (also wrapped as ADK FunctionTools for the LlmAgent)
# ---------------------------------------------------------------------------


def check_return_eligibility(order_number: str) -> dict[str, Any]:
    """
    Mock eligibility: last character of ``order_number`` must be a digit; even -> eligible.

    Returns JSON-serializable dict: ``eligible``, ``reason``.
    """
    s = (order_number or "").strip()
    if not s:
        return {"eligible": False, "reason": "order_number is empty"}
    last = s[-1]
    if not last.isdigit():
        return {
            "eligible": False,
            "reason": "last character is not a digit (mock rule requires a trailing digit)",
        }
    eligible = int(last) % 2 == 0
    reason = (
        "last digit is even - eligible under mock policy"
        if eligible
        else "last digit is odd - not eligible under mock policy"
    )
    return {"eligible": eligible, "reason": reason}


def initiate_return(order_number: str, reason: str) -> dict[str, Any]:
    """Mock creating a return request."""
    rid = f"ret-{uuid.uuid4().hex[:12]}"
    msg = f"Return initiated for order {order_number}"
    if (reason or "").strip():
        msg += f" ({reason.strip()[:500]})"
    return {
        "return_id": rid,
        "status": "initiated",
        "message": msg,
    }


_RETURNS_AGENT_INSTRUCTION = """You are a returns specialist for an online store.

You have two tools:
- check_return_eligibility(order_number) — returns whether the order is eligible (mock rule) with a reason.
- initiate_return(order_number, reason) — creates a mock return request.

When the user asks about eligibility, call check_return_eligibility with the order number they provide.
When they want to start a return, call initiate_return with order number and reason.

Reply in clear, short natural language and include key facts from the tool results.
"""


def build_returns_llm_agent() -> LlmAgent:
    """ADK agent exposed over A2A (tools: eligibility + initiate return)."""
    model = os.getenv("ADK_MODEL", "gemini-2.5-flash")
    return LlmAgent(
        name="returns_agent",
        model=model,
        description="Returns eligibility and return initiation (mock rules).",
        instruction=_RETURNS_AGENT_INSTRUCTION,
        tools=[
            FunctionTool(check_return_eligibility),
            FunctionTool(initiate_return),
        ],
    )


def to_a2a(
    host: str = "127.0.0.1",
    port: int = 8081,
) -> Any:
    """
    ADK pattern: build a **Starlette** ASGI app that speaks A2A (JSON-RPC + agent card).

    Run with::

        uvicorn servers.returns_service.main:starlette_a2a_app --host 127.0.0.1 --port 8081

    ``starlette_a2a_app`` is created on first access (see ``__getattr__`` below).

    This is the same helper as ``google.adk.a2a.utils.agent_to_a2a.to_a2a`` applied to
    :func:`build_returns_llm_agent`.
    """
    agent = build_returns_llm_agent()
    return adk_to_a2a(agent, host=host, port=port, protocol="http")


_starlette_a2a_singleton: Any | None = None


def __getattr__(name: str) -> Any:
    """Lazily build the Starlette A2A app so importing :data:`app` does not spawn a second ASGI stack."""
    global _starlette_a2a_singleton
    if name == "starlette_a2a_app":
        if _starlette_a2a_singleton is None:
            _starlette_a2a_singleton = to_a2a()
        return _starlette_a2a_singleton
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ---------------------------------------------------------------------------
# FastAPI composite app: health, legacy /returns/process, direct tool JSON, + A2A
# ---------------------------------------------------------------------------


class ReturnsProcessBody(BaseModel):
    customer_id: str
    message: str


class CheckEligibilityBody(BaseModel):
    order_number: str


class InitiateReturnBody(BaseModel):
    order_number: str
    reason: str = ""


@asynccontextmanager
async def _lifespan(app: FastAPI):
    agent = build_returns_llm_agent()
    public_base = (os.getenv("RETURNS_A2A_PUBLIC_URL") or "http://127.0.0.1:8081").rstrip("/")
    rpc_url = f"{public_base}/"

    card_builder = AgentCardBuilder(agent=agent, rpc_url=rpc_url)
    agent_card = await card_builder.build()

    async def _create_runner() -> Runner:
        return Runner(
            app_name=agent.name or "returns_service",
            agent=agent,
            artifact_service=InMemoryArtifactService(),
            session_service=InMemorySessionService(),
            memory_service=InMemoryMemoryService(),
            credential_service=InMemoryCredentialService(),
        )

    task_store = InMemoryTaskStore()
    push_config_store = InMemoryPushNotificationConfigStore()
    executor = A2aAgentExecutor(runner=_create_runner)
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=task_store,
        push_config_store=push_config_store,
    )
    a2a_http = A2AFastAPIApplication(agent_card=agent_card, http_handler=handler)
    a2a_http.add_routes_to_app(app)
    yield


app = FastAPI(
    title="Returns Service",
    description="Returns A2A agent + legacy HTTP helpers.",
    lifespan=_lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/returns/process")
async def process_return(payload: ReturnsProcessBody) -> dict[str, str]:
    """Legacy endpoint used by ``ReturnsRemoteAgent`` in the main API."""
    return {
        "result": (
            f"[ReturnsService] Return request noted for `{payload.customer_id}` "
            f"with message: '{payload.message}'. "
            "For structured eligibility/initiation use the A2A agent or /tools/* routes."
        )
    }


@app.post("/tools/check_return_eligibility")
async def tools_check_eligibility(body: CheckEligibilityBody) -> dict[str, Any]:
    """Direct HTTP binding of :func:`check_return_eligibility` (no LLM)."""
    return check_return_eligibility(body.order_number)


@app.post("/tools/initiate_return")
async def tools_initiate_return(body: InitiateReturnBody) -> dict[str, Any]:
    """Direct HTTP binding of :func:`initiate_return` (no LLM)."""
    return initiate_return(body.order_number, body.reason)


def main() -> None:
    """CLI entry: ``python -m servers.returns_service.main``."""
    import uvicorn

    host = os.getenv("RETURNS_SERVICE_HOST", "127.0.0.1")
    port = int(os.getenv("RETURNS_SERVICE_PORT", "8081"))
    uvicorn.run(
        "servers.returns_service.main:app",
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
