"""Unit tests for returns_remote_agent helpers (no live A2A server)."""

import os
import sys
import unittest
import unittest.mock

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)

from src.agents.returns_remote_agent import (  # noqa: E402
    ReturnsRemoteAgent,
    _default_agent_card_url,
    _parse_json_object,
)


class TestParseJsonObject(unittest.TestCase):
    def test_plain_json(self) -> None:
        d = _parse_json_object('{"eligible": true, "reason": "ok"}')
        self.assertTrue(d["eligible"])
        self.assertEqual(d["reason"], "ok")

    def test_fenced_json(self) -> None:
        d = _parse_json_object('```json\n{"a": 1}\n```')
        self.assertEqual(d["a"], 1)

    def test_embedded_braces(self) -> None:
        d = _parse_json_object('Here you go: {"eligible": false, "reason": "x"} thanks')
        self.assertFalse(d["eligible"])


class TestDefaultAgentCardUrl(unittest.TestCase):
    def test_override_env(self) -> None:
        with unittest.mock.patch.dict(
            os.environ,
            {"RETURNS_A2A_AGENT_CARD_URL": "http://example.com/card.json"},
        ):
            self.assertEqual(
                _default_agent_card_url("http://127.0.0.1:8081"),
                "http://example.com/card.json",
            )

    def test_default_suffix(self) -> None:
        with unittest.mock.patch.dict(os.environ, {"RETURNS_A2A_AGENT_CARD_URL": ""}):
            url = _default_agent_card_url("http://127.0.0.1:8081")
            self.assertEqual(
                url,
                "http://127.0.0.1:8081/.well-known/agent-card.json",
            )


class TestReturnsRemoteAgentInit(unittest.TestCase):
    def test_builds_remote_a2a(self) -> None:
        r = ReturnsRemoteAgent("http://127.0.0.1:8081")
        self.assertEqual(r.base_url, "http://127.0.0.1:8081")
        self.assertEqual(r._remote.name, "returns_service_a2a")


if __name__ == "__main__":
    unittest.main()
