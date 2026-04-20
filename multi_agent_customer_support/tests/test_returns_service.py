"""Tests for ``servers/returns_service/main.py`` (FastAPI + mock tools)."""

import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)

from fastapi.testclient import TestClient  # noqa: E402

from servers.returns_service import main as rs  # noqa: E402


class TestReturnsTools(unittest.TestCase):
    def test_eligibility_even_digit(self) -> None:
        r = rs.check_return_eligibility("ORD-42")
        self.assertTrue(r["eligible"])
        self.assertIn("even", r["reason"].lower())

    def test_eligibility_odd_digit(self) -> None:
        r = rs.check_return_eligibility("X-41")
        self.assertFalse(r["eligible"])

    def test_eligibility_non_digit_suffix(self) -> None:
        r = rs.check_return_eligibility("ABC")
        self.assertFalse(r["eligible"])

    def test_initiate_return_shape(self) -> None:
        r = rs.initiate_return("ORD-1", "too big")
        self.assertEqual(r["status"], "initiated")
        self.assertTrue(r["return_id"].startswith("ret-"))
        self.assertIn("ORD-1", r["message"])


class TestReturnsFastAPI(unittest.TestCase):
    """Use ``TestClient`` as a context manager so FastAPI ``lifespan`` runs (A2A route registration)."""

    def test_health(self) -> None:
        with TestClient(rs.app) as client:
            res = client.get("/health")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "ok")

    def test_agent_card(self) -> None:
        with TestClient(rs.app) as client:
            res = client.get("/.well-known/agent-card.json")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("name", data)
        self.assertEqual(data.get("name"), "returns_agent")

    def test_tools_eligibility_endpoint(self) -> None:
        with TestClient(rs.app) as client:
            res = client.post(
                "/tools/check_return_eligibility",
                json={"order_number": "ORD-8"},
            )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["eligible"])

    def test_returns_process_legacy(self) -> None:
        with TestClient(rs.app) as client:
            res = client.post(
                "/returns/process",
                json={"customer_id": "c1", "message": "hello"},
            )
        self.assertEqual(res.status_code, 200)
        self.assertIn("result", res.json())


if __name__ == "__main__":
    unittest.main()
