"""Deterministic draft-review-refine pass for agent responses.

`RouterAgent` can call this after a domain agent returns a raw answer:

    loop = LoopAgent()
    result = loop.process(query=user_message, raw_answer=raw_answer, context={"routed_to": "billing"})
    final_text = result["final_answer"]

This module is intentionally LLM-free so behavior is stable in local development and tests.
"""

from __future__ import annotations

import re
from typing import Any


class LoopAgent:
    """Runs a simple quality loop: draft -> review -> refine."""

    def __init__(self, max_chars: int = 650) -> None:
        """Create a loop agent.

        Args:
            max_chars: Soft target for response length. Refinement trims answers above this limit.
        """
        self._max_chars = max_chars

    def process(self, query: str, raw_answer: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Review and refine a raw answer before it is returned to the user.

        Args:
            query: The user's original question.
            raw_answer: Initial answer produced by the routed domain agent.
            context: Optional routing metadata (for example `{"routed_to": "billing"}`).

        Returns:
            dict with:
              - `final_answer`: refined user-facing text
              - `review_notes`: deterministic notes describing what was checked or changed
        """
        _ = context or {}
        draft = self._generate_draft(raw_answer)
        review_notes = self._review_draft(query=query, draft=draft)
        final_answer = self._refine_draft(draft=draft, review_notes=review_notes)
        return {"final_answer": final_answer, "review_notes": review_notes}

    def _generate_draft(self, raw_answer: str) -> str:
        """Generate the initial draft (currently passthrough)."""
        return (raw_answer or "").strip()

    def _review_draft(self, query: str, draft: str) -> list[str]:
        """Run deterministic quality checks for clarity, tone, and directness."""
        notes: list[str] = []
        lower = draft.lower()

        if "todo" in lower:
            notes.append("Contains TODO marker and needs cleanup.")

        jargon_hits = [term for term in _INTERNAL_JARGON if term in lower]
        if jargon_hits:
            notes.append(f"Contains internal jargon: {', '.join(jargon_hits)}.")

        if len(draft) > self._max_chars:
            notes.append(f"Answer length ({len(draft)}) exceeds target ({self._max_chars}).")

        # Clarity: flag very long single-paragraph responses.
        if len(draft) > 220 and "\n" not in draft and ". " in draft:
            notes.append("Could be clearer with shorter phrasing.")

        # Tone: keep concise and friendly.
        if not _looks_friendly(draft):
            notes.append("Tone may feel abrupt; make it friendlier.")

        # Directness: lightweight heuristic based on keyword overlap.
        if not _directly_addresses_query(query=query, answer=draft):
            notes.append("May not directly answer the user's question.")

        if not notes:
            notes.append("Review passed: clear, concise, and directly answers the question.")

        return notes

    def _refine_draft(self, draft: str, review_notes: list[str]) -> str:
        """Apply deterministic refinements based on review notes."""
        refined = draft

        # Remove placeholder TODOs.
        refined = re.sub(r"\bTODO\b[:\- ]*", "", refined, flags=re.IGNORECASE)

        # Replace known internal jargon with plain language.
        for bad, plain in _JARGON_REPLACEMENTS.items():
            refined = re.sub(rf"\b{re.escape(bad)}\b", plain, refined, flags=re.IGNORECASE)

        # Add a soft-friendly opener only if the text is short and blunt.
        if "Tone may feel abrupt; make it friendlier." in review_notes and refined:
            if not _looks_friendly(refined):
                refined = f"Happy to help. {refined}"

        # Keep under a soft character budget where possible.
        if len(refined) > self._max_chars:
            cutoff = refined[: self._max_chars].rstrip()
            last_sentence = cutoff.rfind(". ")
            if last_sentence > 120:
                refined = cutoff[: last_sentence + 1]
            else:
                refined = f"{cutoff}..."

        # Final whitespace cleanup.
        return re.sub(r"\s{2,}", " ", refined).strip()


_INTERNAL_JARGON = {
    "mcp",
    "json-rpc",
    "remotea2aagent",
    "llmagent",
    "tool call",
    "functiontool",
}

_JARGON_REPLACEMENTS = {
    "mcp": "the service",
    "json-rpc": "the integration channel",
    "remotea2aagent": "the returns service",
    "llmagent": "the assistant",
    "functiontool": "tooling",
}


def _looks_friendly(text: str) -> bool:
    """Heuristic for friendly tone."""
    lower = text.lower()
    return any(token in lower for token in ("please", "happy to help", "thanks", "glad", "certainly"))


def _directly_addresses_query(query: str, answer: str) -> bool:
    """Lightweight check that answer overlaps the user query topic."""
    query_words = {w for w in re.findall(r"[a-zA-Z]{4,}", query.lower())}
    answer_words = {w for w in re.findall(r"[a-zA-Z]{4,}", answer.lower())}
    if not query_words:
        return bool(answer.strip())
    overlap = query_words.intersection(answer_words)
    return len(overlap) >= 1
