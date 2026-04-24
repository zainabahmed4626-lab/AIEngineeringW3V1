"""FastAPI service exposing the full support system as an A2A HTTP endpoint.

This differs from `src.main`:
- `src.main` is an internal API/CLI entrypoint for local interactive use.
- This service is an externalized A2A endpoint so other services can call one high-level tool:
  `handle_support_query(query)`.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from a2a.server.apps import A2AFastAPIApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryPushNotificationConfigStore
from a2a.server.tasks import InMemoryTaskStore
from dotenv import load_dotenv
from fastapi import FastAPI
from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor
from google.adk.a2a.utils.agent_card_builder import AgentCardBuilder
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.auth.credential_service.in_memory_credential_service import (
    InMemoryCredentialService,
)
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from pydantic import BaseModel

from src.a2a.support_system_a2a import build_support_system_llm_agent, handle_support_query

_WORKSPACE_ENV = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(_WORKSPACE_ENV)


class SupportQueryBody(BaseModel):
    query: str


@asynccontextmanager
async def _lifespan(app: FastAPI):
    agent = build_support_system_llm_agent()
    public_base = (os.getenv("SUPPORT_SYSTEM_A2A_PUBLIC_URL") or "http://127.0.0.1:8082").rstrip("/")
    rpc_url = f"{public_base}/"

    card_builder = AgentCardBuilder(agent=agent, rpc_url=rpc_url)
    agent_card = await card_builder.build()

    async def _create_runner() -> Runner:
        return Runner(
            app_name=agent.name or "support_system_service",
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
    title="Support System Service",
    description="A2A wrapper around RouterAgent + specialists + LoopAgent.",
    lifespan=_lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/tools/handle_support_query")
async def tools_handle_support_query(body: SupportQueryBody) -> dict[str, Any]:
    """Direct HTTP helper for the same tool exposed via A2A JSON-RPC."""
    return await handle_support_query(body.query)


@app.get("/docs/how-to-call")
async def how_to_call() -> dict[str, str]:
    """Quick HTTP/A2A call examples for clients."""
    return {
        "tool_http": "POST /tools/handle_support_query with JSON body: {\"query\": \"...\"}",
        "agent_card": "GET /.well-known/agent-card.json",
        "a2a_rpc": "POST / with JSON-RPC method message/send",
    }


def main() -> None:
    """CLI entry: `python -m servers.support_system_service.main`."""
    import uvicorn

    host = os.getenv("SUPPORT_SYSTEM_SERVICE_HOST", "127.0.0.1")
    port = int(os.getenv("SUPPORT_SYSTEM_SERVICE_PORT", "8082"))
    uvicorn.run(
        "servers.support_system_service.main:app",
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
