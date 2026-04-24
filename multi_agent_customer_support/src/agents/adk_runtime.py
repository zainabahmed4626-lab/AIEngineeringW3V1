"""Shared helpers for running ADK ``LlmAgent`` instances with ``Runner`` (stdio-free)."""

from __future__ import annotations

import logging
import uuid
from typing import TypeVar

from google.adk.agents.base_agent import BaseAgent
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.auth.credential_service.in_memory_credential_service import (
    InMemoryCredentialService,
)
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types
from pydantic import BaseModel

logger = logging.getLogger(__name__)

TModel = TypeVar("TModel", bound=BaseModel)


def genai_api_configured() -> bool:
    """True when Gemini Developer API keys are present (same convention as google-genai)."""
    import os

    return bool(os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"))


def looks_like_genai_quota_error(exc: BaseException) -> bool:
    """
    True when ``exc`` is likely a Gemini / Google GenAI quota or rate-limit failure.

    Used to fall back to deterministic tool paths so local UIs keep working when the
    free tier is exhausted (HTTP 429 / RESOURCE_EXHAUSTED).
    """
    text = f"{type(exc).__name__} {exc!s}".lower()
    return any(
        m in text
        for m in (
            "resource_exhausted",
            "429",
            "quota",
            "rate limit",
            "too many requests",
            "exhausted",
        )
    )


async def run_llm_agent_once(
    *,
    agent: BaseAgent,
    user_message: str,
    app_name: str,
    user_id: str | None = None,
) -> str:
    """
    Run a single-turn conversation: one user message in, final model text out.

    Uses an ephemeral session id so concurrent FastAPI requests do not share history.
    """
    session_service = InMemorySessionService()
    runner = Runner(
        app_name=app_name,
        agent=agent,
        artifact_service=InMemoryArtifactService(),
        session_service=session_service,
        memory_service=InMemoryMemoryService(),
        credential_service=InMemoryCredentialService(),
        auto_create_session=True,
    )
    session_id = str(uuid.uuid4())
    uid = user_id or "anonymous"

    content = types.Content(
        role="user",
        parts=[types.Part(text=user_message)],
    )

    final_text = ""
    async for event in runner.run_async(
        user_id=uid,
        session_id=session_id,
        new_message=content,
    ):
        if not event.is_final_response():
            continue
        if not event.content or not event.content.parts:
            continue
        chunk = "".join(
            part.text
            for part in event.content.parts
            if part.text and not getattr(part, "thought", False)
        )
        if chunk.strip():
            final_text = chunk

    return final_text.strip()


async def run_router_structured(
    *,
    agent: BaseAgent,
    user_message: str,
    schema_type: type[TModel],
    app_name: str = "router",
) -> TModel | None:
    """
    Run router agent expecting structured JSON matching ``schema_type``.

    Returns ``None`` if the model returns empty/unparseable output (caller should fall back).
    """
    try:
        raw = await run_llm_agent_once(
            agent=agent,
            user_message=user_message,
            app_name=app_name,
        )
    except Exception as exc:
        if looks_like_genai_quota_error(exc):
            logger.warning("Router LLM quota/rate limit hit; caller should use heuristic fallback: %s", exc)
            return None
        raise
    if not raw:
        return None
    try:
        return schema_type.model_validate_json(raw)
    except Exception as exc:
        logger.warning(
            "Failed to parse router output as %s: %s — raw: %s",
            schema_type,
            exc,
            raw[:500],
        )
        return None
